from __future__ import annotations

import json
import socket
import struct
import threading
from dataclasses import dataclass
from typing import Callable

from ..util import now_ms


DEFAULT_DISCOVERY_PORT = 37020
DISCOVERY_MULTICAST_GROUP = "239.255.37.20"


@dataclass(frozen=True)
class Beacon:
    peer_id: str
    nickname: str
    udp_port: int
    tcp_port: int
    ts_ms: int


class UdpDiscovery:
    def __init__(
        self,
        udp_port: int,
        get_local_ip: Callable[[], str],
        beacon_factory: Callable[[], Beacon],
        on_beacon: Callable[[str, Beacon], None],
    ) -> None:
        self._udp_port = udp_port
        self._get_local_ip = get_local_ip
        self._beacon_factory = beacon_factory
        self._on_beacon = on_beacon

        self._stop = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    @property
    def udp_port(self) -> int:
        return self._udp_port

    def start(self) -> None:
        if self._sock is not None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        except OSError:
            pass
        sock.bind(("", self._udp_port))
        try:
            mreq = struct.pack("=4s4s", socket.inet_aton(DISCOVERY_MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass
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

    def send_to(self, ip: str, port: int, beacon: Beacon | None = None) -> None:
        """向指定地址发送 beacon（用于主动探测节点）"""
        if self._sock is None:
            return
        if beacon is None:
            beacon = self._beacon_factory()
        payload = json.dumps(
            {
                "type": "beacon",
                "peer_id": beacon.peer_id,
                "nickname": beacon.nickname,
                "udp_port": beacon.udp_port,
                "tcp_port": beacon.tcp_port,
                "ts_ms": now_ms(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self._sock.sendto(payload, (ip, port))
        except OSError:
            pass

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
                    "udp_port": beacon.udp_port,
                    "tcp_port": beacon.tcp_port,
                    "ts_ms": now_ms(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            for target in _probe_targets(local_ip, self._udp_port):
                try:
                    self._sock.sendto(payload, target)
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
                    udp_port=int(msg.get("udp_port", 0) or msg.get("tcp_port", 0)),
                    tcp_port=int(msg.get("tcp_port", 0)),
                    ts_ms=int(msg.get("ts_ms", 0)),
                )
            except Exception:
                continue
            if not beacon.peer_id or beacon.udp_port <= 0 or beacon.udp_port > 65535:
                continue
            self._on_beacon(ip, beacon)


def _probe_targets(local_ip: str, local_port: int) -> list[tuple[str, int]]:
    """生成广播目标地址列表"""
    # 广播目标 IP
    target_ips: list[str] = ["255.255.255.255", DISCOVERY_MULTICAST_GROUP, "127.0.0.1"]
    parts = local_ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b, c, d = [int(p) for p in parts]
        if all(0 <= x <= 255 for x in (a, b, c, d)):
            if not local_ip.startswith("127."):
                target_ips.append(local_ip)
                target_ips.append(f"{a}.{b}.{c}.255")
                target_ips.append(f"{a}.{b}.255.255")
            if a == 10:
                target_ips.append("10.255.255.255")
            elif a == 172 and 16 <= b <= 31:
                target_ips.append("172.31.255.255")
            elif a == 192 and b == 168:
                target_ips.append("192.168.255.255")

    # 去重并生成 (ip, port) 元组
    seen: set[str] = set()
    targets: list[tuple[str, int]] = []
    for ip in target_ips:
        if ip in seen:
            continue
        seen.add(ip)
        targets.append((ip, local_port))
    return targets
