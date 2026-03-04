from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeerInfo:
    peer_id: str
    ip: str
    port: int
    nickname: str
    last_seen_ms: int

    def key(self) -> str:
        return f"{self.ip}:{self.port}"

