from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..model.peer import PeerInfo
from ..util import Addr, guess_local_ip, now_ms
from .discovery import Beacon, UdpDiscovery
from .protocol import decode_frames, encode_frame


@dataclass(frozen=True)
class NodeConfig:
    peer_id: str
    nickname: str


@dataclass(frozen=True)
class NodeEvent:
    type: str
    payload: dict[str, Any]


class Node:
    def __init__(
        self,
        cfg: NodeConfig,
        on_event: Callable[[NodeEvent], None],
        *,
        enable_discovery: bool = True,
    ) -> None:
        self.cfg = cfg
        self._on_event = on_event
        self._enable_discovery = enable_discovery

        self.local_ip = guess_local_ip()
        self.listen_addr: Addr | None = None

        self._stop = threading.Event()
        self._tcp_server: socket.socket | None = None
        self._tcp_thread: threading.Thread | None = None

        self._discovery: UdpDiscovery | None = None

        self._peers_lock = threading.Lock()
        self._peers_by_id: dict[str, PeerInfo] = {}
        self._outgoing_lock = threading.Lock()
        self._connections: dict[str, "PeerConn"] = {}

        self._tick_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._tcp_server is not None:
            return

        self._tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_server.bind(("", 0))
        self._tcp_server.listen(50)
        self._tcp_server.settimeout(0.5)
        host, port = self._tcp_server.getsockname()[:2]
        self.listen_addr = Addr(self.local_ip, int(port))

        self._tcp_thread = threading.Thread(target=self._accept_loop, name="tcp-accept", daemon=True)
        self._tcp_thread.start()

        if self._enable_discovery:
            self._discovery = UdpDiscovery(
                get_local_ip=lambda: self.local_ip,
                beacon_factory=self._make_beacon,
                on_beacon=self._on_beacon,
            )
            self._discovery.start()

        self._tick_thread = threading.Thread(target=self._tick_loop, name="node-tick", daemon=True)
        self._tick_thread.start()

        self._emit(
            "node_started",
            {
                "peer_id": self.cfg.peer_id,
                "nickname": self.cfg.nickname,
                "ip": self.local_ip,
                "port": self.listen_addr.port,
            },
        )

    def stop(self) -> None:
        self._stop.set()
        if self._discovery is not None:
            self._discovery.stop()
        if self._tcp_server is not None:
            try:
                self._tcp_server.close()
            except OSError:
                pass
        self._tcp_server = None
        with self._outgoing_lock:
            conns = list(self._connections.values())
            self._connections.clear()
        for c in conns:
            c.close()

    def update_nickname(self, nickname: str) -> None:
        self.cfg = NodeConfig(peer_id=self.cfg.peer_id, nickname=nickname)
        self._broadcast_peers()

    def peers_snapshot(self) -> list[PeerInfo]:
        with self._peers_lock:
            return list(self._peers_by_id.values())

    def connect_to(self, ip: str, port: int) -> None:
        if not ip or port <= 0:
            return
        if self.listen_addr and ip == self.local_ip and port == self.listen_addr.port:
            return
        key = f"{ip}:{port}"
        with self._outgoing_lock:
            if key in self._connections:
                return

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.2)
            sock.connect((ip, port))
            sock.settimeout(0.5)
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            return

        conn = PeerConn(
            sock=sock,
            addr=Addr(ip, port),
            on_message=lambda msg, a=Addr(ip, port): self._on_tcp_message(a, msg),
            on_close=lambda a=Addr(ip, port): self._on_tcp_close(a),
        )
        with self._outgoing_lock:
            self._connections[key] = conn
        conn.start()

        self._send_hello(conn)

    def broadcast(self, msg: dict[str, Any]) -> None:
        with self._outgoing_lock:
            conns = list(self._connections.values())
        for c in conns:
            c.send(msg)

    def send_to_peer(self, peer_id: str, msg: dict[str, Any]) -> None:
        if not peer_id or peer_id == self.cfg.peer_id:
            return
        with self._peers_lock:
            p = self._peers_by_id.get(peer_id)
        if p is None:
            return
        self.connect_to(p.ip, p.port)
        key = f"{p.ip}:{p.port}"
        with self._outgoing_lock:
            conn = self._connections.get(key)
        if conn is not None:
            conn.send(msg)

    def _accept_loop(self) -> None:
        assert self._tcp_server is not None
        while not self._stop.is_set():
            try:
                client, addr = self._tcp_server.accept()
            except socket.timeout:
                continue
            except OSError:
                return

            ip, port = addr[0], addr[1]
            client.settimeout(0.5)
            a = Addr(ip, int(port))
            conn = PeerConn(
                sock=client,
                addr=a,
                on_message=lambda msg, aa=a: self._on_tcp_message(aa, msg),
                on_close=lambda aa=a: self._on_tcp_close(aa),
            )
            with self._outgoing_lock:
                self._connections[a.key()] = conn
            conn.start()

    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            self._drop_stale_peers()
            self._broadcast_peers()
            self._stop.wait(2.5)

    def _drop_stale_peers(self) -> None:
        cutoff = now_ms() - 15_000
        removed: list[str] = []
        with self._peers_lock:
            for pid, p in list(self._peers_by_id.items()):
                if p.last_seen_ms < cutoff:
                    removed.append(pid)
                    del self._peers_by_id[pid]
        if removed:
            self._emit("peers_changed", {})

    def _make_beacon(self) -> Beacon:
        assert self.listen_addr is not None
        return Beacon(
            peer_id=self.cfg.peer_id,
            nickname=self.cfg.nickname,
            tcp_port=self.listen_addr.port,
            ts_ms=now_ms(),
        )

    def _on_beacon(self, ip: str, beacon: Beacon) -> None:
        if beacon.peer_id == self.cfg.peer_id:
            return

        changed = False
        with self._peers_lock:
            existing = self._peers_by_id.get(beacon.peer_id)
            if existing is None or existing.ip != ip or existing.port != beacon.tcp_port or existing.nickname != beacon.nickname:
                changed = True
            self._peers_by_id[beacon.peer_id] = PeerInfo(
                peer_id=beacon.peer_id,
                ip=ip,
                port=beacon.tcp_port,
                nickname=beacon.nickname,
                last_seen_ms=now_ms(),
            )
        if changed:
            self._emit("peers_changed", {})

        self.connect_to(ip, beacon.tcp_port)

    def _send_hello(self, conn: "PeerConn") -> None:
        assert self.listen_addr is not None
        conn.send(
            {
                "type": "hello",
                "peer_id": self.cfg.peer_id,
                "nickname": self.cfg.nickname,
                "ip": self.local_ip,
                "port": self.listen_addr.port,
            }
        )
        conn.send({"type": "peers", "items": self._peers_compact()})

    def _broadcast_peers(self) -> None:
        items = self._peers_compact()
        with self._outgoing_lock:
            conns = list(self._connections.values())
        for c in conns:
            c.send({"type": "peers", "items": items})

    def _peers_compact(self) -> list[dict[str, Any]]:
        with self._peers_lock:
            peers = list(self._peers_by_id.values())
        return [
            {"peer_id": p.peer_id, "ip": p.ip, "port": p.port, "nickname": p.nickname, "last_seen_ms": p.last_seen_ms}
            for p in peers
        ]

    def _on_tcp_message(self, addr: Addr, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "hello":
            pid = str(msg.get("peer_id", ""))
            if not pid or pid == self.cfg.peer_id:
                return
            ip = str(msg.get("ip", addr.ip))
            port = int(msg.get("port", 0) or 0)
            nick = str(msg.get("nickname", ""))
            if port <= 0 or port > 65535:
                return
            with self._peers_lock:
                self._peers_by_id[pid] = PeerInfo(
                    peer_id=pid,
                    ip=ip,
                    port=port,
                    nickname=nick or "玩家",
                    last_seen_ms=now_ms(),
                )
            self._emit("peers_changed", {})
            self.connect_to(ip, port)
            return

        if mtype == "peers":
            items = msg.get("items")
            if not isinstance(items, list):
                return
            changed = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("peer_id", ""))
                if not pid or pid == self.cfg.peer_id:
                    continue
                ip = str(item.get("ip", ""))
                port = int(item.get("port", 0) or 0)
                nick = str(item.get("nickname", ""))
                last_seen = int(item.get("last_seen_ms", 0) or 0)
                if not ip or port <= 0 or port > 65535:
                    continue
                with self._peers_lock:
                    existing = self._peers_by_id.get(pid)
                    if existing is None or existing.ip != ip or existing.port != port or existing.nickname != nick:
                        changed = True
                    self._peers_by_id[pid] = PeerInfo(
                        peer_id=pid,
                        ip=ip,
                        port=port,
                        nickname=nick or "玩家",
                        last_seen_ms=max(now_ms(), last_seen),
                    )
                self.connect_to(ip, port)
            if changed:
                self._emit("peers_changed", {})
            return

        self._emit("net_message", {"from": addr.key(), "message": msg})

    def _on_tcp_close(self, addr: Addr) -> None:
        key = addr.key()
        with self._outgoing_lock:
            self._connections.pop(key, None)

    def _emit(self, etype: str, payload: dict[str, Any]) -> None:
        try:
            self._on_event(NodeEvent(type=etype, payload=payload))
        except Exception:
            pass


class PeerConn:
    def __init__(
        self,
        sock: socket.socket,
        addr: Addr,
        on_message: Callable[[dict[str, Any]], None],
        on_close: Callable[[], None],
    ) -> None:
        self.sock = sock
        self.addr = addr
        self._on_message = on_message
        self._on_close = on_close
        self._stop = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._txq: "queue.Queue[bytes]" = queue.Queue()
        self._buf = bytearray()

    def start(self) -> None:
        self._rx_thread = threading.Thread(target=self._rx_loop, name=f"tcp-rx-{self.addr.key()}", daemon=True)
        self._tx_thread = threading.Thread(target=self._tx_loop, name=f"tcp-tx-{self.addr.key()}", daemon=True)
        self._rx_thread.start()
        self._tx_thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            self._on_close()
        except Exception:
            pass

    def send(self, msg: dict[str, Any]) -> None:
        try:
            self._txq.put_nowait(encode_frame(msg))
        except Exception:
            pass

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self._buf.extend(chunk)
            try:
                msgs = decode_frames(self._buf)
            except Exception:
                break
            for m in msgs:
                try:
                    self._on_message(m)
                except Exception:
                    continue
        self.close()

    def _tx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._txq.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.sock.sendall(payload)
            except OSError:
                break
        self.close()
