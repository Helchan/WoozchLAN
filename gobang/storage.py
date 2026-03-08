from __future__ import annotations

import json
import os
from dataclasses import dataclass

try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None  # type: ignore

try:
    import msvcrt  # type: ignore
except Exception:
    msvcrt = None  # type: ignore

from . import __version__
from .util import get_data_dir, new_id


@dataclass(frozen=True)
class Settings:
    peer_id: str
    nickname: str
    version: str = __version__


_lock_fds: list[int] = []


def _settings_path() -> str:
    return os.path.join(get_data_dir("gobang"), "settings.json")


def load_settings() -> Settings:
    path = _settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        peer_id = str(raw.get("peer_id", "")).strip()
        nickname = str(raw.get("nickname", "")).strip()
        version = str(raw.get("version", __version__)).strip()
        if peer_id and nickname:
            return Settings(peer_id=peer_id, nickname=nickname, version=version)
    except Exception:
        pass
    nick = f"玩家{new_id()[:4]}"
    return Settings(peer_id=new_id(), nickname=nick, version=__version__)


def save_settings(s: Settings) -> None:
    path = _settings_path()
    tmp = path + ".tmp"
    payload = {"peer_id": s.peer_id, "nickname": s.nickname, "version": s.version}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def allocate_runtime_settings(base: Settings) -> tuple[Settings, bool]:
    try:
        base_dir = get_data_dir("gobang")
        locks_dir = os.path.join(base_dir, "locks")
        os.makedirs(locks_dir, exist_ok=True)
    except Exception:
        runtime_peer_id = new_id()
        nick = base.nickname
        if nick and "（" not in nick:
            nick = f"{nick}（副本）"
        return Settings(peer_id=runtime_peer_id, nickname=nick or base.nickname), True

    def try_lock(pid: str) -> int | None:
        path = os.path.join(locks_dir, f"peer-{pid}.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                raise RuntimeError("no file lock implementation")
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            return fd
        except BlockingIOError:
            os.close(fd)
            return None
        except OSError:
            os.close(fd)
            return None

    fd = try_lock(base.peer_id)
    if fd is not None:
        _lock_fds.append(fd)
        return base, False

    runtime_peer_id = new_id()
    fd2 = try_lock(runtime_peer_id)
    if fd2 is not None:
        _lock_fds.append(fd2)
    nick = base.nickname
    if nick and "（" not in nick:
        nick = f"{nick}（副本）"
    return Settings(peer_id=runtime_peer_id, nickname=nick or base.nickname), True


def _release_runtime_locks_for_tests() -> None:
    while _lock_fds:
        fd = _lock_fds.pop()
        try:
            os.close(fd)
        except OSError:
            pass
