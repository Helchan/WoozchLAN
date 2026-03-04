from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoomSummary:
    room_id: str
    name: str
    host_peer_id: str
    host_nickname: str
    host_ip: str
    host_port: int
    status: str  # waiting|playing
    player2_peer_id: str | None
    player2_nickname: str | None
    players: int
    spectators: int
    updated_ms: int


@dataclass
class RoomHostState:
    room_id: str
    name: str
    host_peer_id: str
    host_nickname: str
    host_ip: str
    host_port: int
    status: str = "waiting"
    player2_peer_id: str | None = None
    player2_nickname: str | None = None
    spectators: set[str] = field(default_factory=set)
    nicknames: dict[str, str] = field(default_factory=dict)
    ready: dict[str, bool] = field(default_factory=dict)
    created_ms: int = 0
    updated_ms: int = 0

    def participants(self) -> dict[str, object]:
        return {
            "host_peer_id": self.host_peer_id,
            "player2_peer_id": self.player2_peer_id,
            "spectators": sorted(self.spectators),
            "ready": dict(self.ready),
            "nicknames": dict(self.nicknames),
        }

    def summary(self) -> RoomSummary:
        return RoomSummary(
            room_id=self.room_id,
            name=self.name,
            host_peer_id=self.host_peer_id,
            host_nickname=self.host_nickname,
            host_ip=self.host_ip,
            host_port=self.host_port,
            status=self.status,
            player2_peer_id=self.player2_peer_id,
            player2_nickname=self.player2_nickname,
            players=1 + (1 if self.player2_peer_id else 0),
            spectators=len(self.spectators),
            updated_ms=self.updated_ms,
        )
