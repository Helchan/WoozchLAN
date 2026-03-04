from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from typing import Callable

from ..util import now_ms


DISCOVERY_PORT = 37020


@dataclass(frozen=True)
class Beacon:
    peer_id: str
    nickname: str
    tcp_port: int
    ts_ms: int


class UdpDiscovery:
    def __init__(
        self,
        get_local_ip: Callable[[], str],
        beacon_factory: Callable[[], Beacon],
        on_beacon: Callable[[str, Beacon], None],
    ) -> None:
        self._get_local_ip = get_local_ip
        self._beacon_factory = beacon_factory
        self._on_beacon = on_beacon

        self._stop = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    def start(self) -> None:
        if self._sock is not None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(0.5)
        self._sock = sock

        self._rx_thread = threading.Thread(target=self._rx_loop, name="udp-discovery-rx", daemon=True)
        self._tx_thread = threading.Thread(target=self._tx_loop, name="udp-discovery-tx", daemon=True)
        self._rx_thread.start()
        self._tx_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _tx_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            beacon = self._beacon_factory()
            local_ip = self._get_local_ip()
            payload = json.dumps(
                {
                    "type": "beacon",
                    "peer_id": beacon.peer_id,
                    "nickname": beacon.nickname,
                    "tcp_port": beacon.tcp_port,
                    "ts_ms": now_ms(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            try:
                self._sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                pass
            if local_ip and not local_ip.startswith("127."):
                try:
                    self._sock.sendto(payload, (local_ip, DISCOVERY_PORT))
                except OSError:
                    pass
            try:
                self._sock.sendto(payload, ("127.0.0.1", DISCOVERY_PORT))
            except OSError:
                pass
            self._stop.wait(1.2)

    def _rx_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(64 * 1024)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(msg, dict) or msg.get("type") != "beacon":
                continue

            ip = addr[0]
            try:
                beacon = Beacon(
                    peer_id=str(msg.get("peer_id", "")),
                    nickname=str(msg.get("nickname", "")),
                    tcp_port=int(msg.get("tcp_port", 0)),
                    ts_ms=int(msg.get("ts_ms", 0)),
                )
            except Exception:
                continue
            if not beacon.peer_id or beacon.tcp_port <= 0 or beacon.tcp_port > 65535:
                continue
            self._on_beacon(ip, beacon)
