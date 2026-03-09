from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeerInfo:
    peer_id: str
    ip: str
    port: int  # TCP 端口
    udp_port: int  # UDP 端口（用于节点发现）
    nickname: str
    last_seen_ms: int

    def key(self) -> str:
        return f"{self.ip}:{self.port}"

