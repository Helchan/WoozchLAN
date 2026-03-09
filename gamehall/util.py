from __future__ import annotations

import os
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from typing import IO


# 单例锁文件句柄，全局保持打开以维持锁
_lock_file_handle: IO[str] | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


def get_app_root() -> str:
    """获取程序根目录（gamehall 包的上级目录）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_lock_file_path() -> str:
    """获取锁文件路径"""
    return os.path.join(get_app_root(), ".heyou.lock")


def acquire_instance_lock() -> bool:
    """
    尝试获取单例锁，防止同一程序目录下多开。
    返回 True 表示成功获取锁，False 表示已有实例运行。
    """
    global _lock_file_handle
    lock_path = get_lock_file_path()
    
    try:
        # 打开或创建锁文件
        _lock_file_handle = open(lock_path, "w", encoding="utf-8")
        
        # 尝试获取独占锁
        if sys.platform == "win32":
            # Windows
            import msvcrt
            try:
                msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except IOError:
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
        else:
            # Unix/macOS
            import fcntl
            try:
                fcntl.flock(_lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # 写入 PID 以便调试
                _lock_file_handle.write(str(os.getpid()))
                _lock_file_handle.flush()
                return True
            except (IOError, OSError):
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
    except Exception:
        if _lock_file_handle:
            try:
                _lock_file_handle.close()
            except Exception:
                pass
            _lock_file_handle = None
        return False


def release_instance_lock() -> None:
    """释放单例锁"""
    global _lock_file_handle
    if _lock_file_handle is not None:
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(_lock_file_handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            _lock_file_handle.close()
        except Exception:
            pass
        _lock_file_handle = None
        
        # 尝试删除锁文件
        try:
            os.remove(get_lock_file_path())
        except Exception:
            pass


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
