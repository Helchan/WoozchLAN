from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoomSummary:
    """房间摘要信息，用于大厅列表显示"""
    room_id: str
    name: str
    host_peer_id: str
    host_nickname: str
    host_ip: str
    host_port: int
    status: str  # waiting | playing
    team_a_count: int  # A方人数
    team_b_count: int  # B方人数
    team_size: int  # 每方需要的人数
    players: int  # 总玩家数（兼容字段）
    spectators: int
    updated_ms: int
    game: str = "gomoku"


@dataclass
class RoomHostState:
    """房主视角的房间状态"""
    room_id: str
    name: str
    host_peer_id: str
    host_nickname: str
    host_ip: str
    host_port: int
    game: str = "gomoku"
    status: str = "waiting"  # waiting | playing
    team_size: int = 1  # 每方需要的人数，1v1 为 1，2v2 为 2
    team_a: list[str] = field(default_factory=list)  # A方玩家（房主方）
    team_b: list[str] = field(default_factory=list)  # B方玩家
    spectators: set[str] = field(default_factory=set)
    nicknames: dict[str, str] = field(default_factory=dict)
    ready: dict[str, bool] = field(default_factory=dict)
    created_ms: int = 0
    updated_ms: int = 0

    def __post_init__(self) -> None:
        """确保房主在 team_a 中"""
        if self.host_peer_id and self.host_peer_id not in self.team_a:
            self.team_a.insert(0, self.host_peer_id)

    def participants(self) -> dict[str, object]:
        """获取参与者信息，用于广播"""
        return {
            "host_peer_id": self.host_peer_id,
            "team_a": list(self.team_a),
            "team_b": list(self.team_b),
            "team_size": self.team_size,
            "spectators": sorted(self.spectators),
            "ready": dict(self.ready),
            "nicknames": dict(self.nicknames),
            # 兼容字段
            "player2_peer_id": self.team_b[0] if self.team_b else None,
        }

    def summary(self) -> RoomSummary:
        """生成房间摘要"""
        return RoomSummary(
            room_id=self.room_id,
            name=self.name,
            host_peer_id=self.host_peer_id,
            host_nickname=self.host_nickname,
            host_ip=self.host_ip,
            host_port=self.host_port,
            status=self.status,
            team_a_count=len(self.team_a),
            team_b_count=len(self.team_b),
            team_size=self.team_size,
            players=len(self.team_a) + len(self.team_b),
            spectators=len(self.spectators),
            updated_ms=self.updated_ms,
            game=self.game,
        )

    def is_team_a_full(self) -> bool:
        """A方是否已满"""
        return len(self.team_a) >= self.team_size

    def is_team_b_full(self) -> bool:
        """B方是否已满"""
        return len(self.team_b) >= self.team_size

    def is_both_teams_full(self) -> bool:
        """双方是否都已满"""
        return self.is_team_a_full() and self.is_team_b_full()

    def is_team_b_all_ready(self) -> bool:
        """B方是否全部准备就绪"""
        if not self.team_b:
            return False
        return all(self.ready.get(pid, False) for pid in self.team_b)

    def can_start_game(self) -> bool:
        """是否可以开始游戏"""
        return self.is_both_teams_full() and self.is_team_b_all_ready()

    def get_player_team(self, peer_id: str) -> str | None:
        """获取玩家所在队伍"""
        if peer_id in self.team_a:
            return "team_a"
        if peer_id in self.team_b:
            return "team_b"
        return None

    def remove_player(self, peer_id: str) -> bool:
        """移除玩家，返回是否成功移除"""
        if peer_id in self.team_a and peer_id != self.host_peer_id:
            self.team_a.remove(peer_id)
            self.ready.pop(peer_id, None)
            self.nicknames.pop(peer_id, None)
            return True
        if peer_id in self.team_b:
            self.team_b.remove(peer_id)
            self.ready.pop(peer_id, None)
            self.nicknames.pop(peer_id, None)
            return True
        if peer_id in self.spectators:
            self.spectators.discard(peer_id)
            self.ready.pop(peer_id, None)
            self.nicknames.pop(peer_id, None)
            return True
        return False
