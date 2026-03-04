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


def get_data_dir(app_name: str = "gomoku_lan") -> str:
    override = os.environ.get("GOMOKU_LAN_DATA_DIR", "").strip()
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


@dataclass(frozen=True)
class Addr:
    ip: str
    port: int

    def as_tuple(self) -> tuple[str, int]:
        return (self.ip, self.port)

    def key(self) -> str:
        return f"{self.ip}:{self.port}"
