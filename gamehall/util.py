from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


def get_app_root() -> str:
    """获取程序根目录（gamehall 包的上级目录）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir(app_name: str = "gobang") -> str:
    override = os.environ.get("GOBANG_DATA_DIR", "").strip()
    if override:
        path = override
    else:
        base = os.path.expanduser("~")
        path = os.path.join(base, f".{app_name}")
    os.makedirs(path, exist_ok=True)
    return path


def guess_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        finally:
            s.close()
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        candidates = socket.gethostbyname_ex(hostname)[2]
        for ip in candidates:
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    return "127.0.0.1"


def is_udp_port_available(port: int) -> bool:
    """检测 UDP 端口是否可用"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.close()
        return True
    except OSError:
        return False


def allocate_udp_port(start_port: int = 37020, max_attempts: int = 100) -> int:
    """从 start_port 开始分配可用的 UDP 端口"""
    for i in range(max_attempts):
        port = start_port + i
        if is_udp_port_available(port):
            return port
    raise RuntimeError(f"无法分配 UDP 端口（尝试了 {start_port} 到 {start_port + max_attempts - 1}）")


@dataclass(frozen=True)
class Addr:
    ip: str
    port: int

    def as_tuple(self) -> tuple[str, int]:
        return (self.ip, self.port)

    def key(self) -> str:
        return f"{self.ip}:{self.port}"
