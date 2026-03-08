"""五子棋游戏处理器"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .base import GameConfig, GameHandler
from .registry import GameRegistry


BOARD_SIZE = 15


@dataclass
class GomokuState:
    """五子棋游戏状态"""
    board: list[list[int]]  # 棋盘，0=空, 1=黑, 2=白
    next_peer_id: str  # 下一个落子的玩家
    winner_peer_id: str | None = None  # 获胜者
    last_move: tuple[int, int, int] | None = None  # (x, y, color)
    colors: dict[str, int] | None = None  # peer_id -> color (1=黑, 2=白)

    @staticmethod
    def new(next_peer_id: str) -> "GomokuState":
        return GomokuState(
            board=[[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)],
            next_peer_id=next_peer_id,
        )

    def can_place(self, x: int, y: int) -> bool:
        return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and self.board[y][x] == 0


def check_winner(board: list[list[int]], x: int, y: int) -> int:
    """检查是否有玩家获胜，返回获胜方颜色（1或2），无获胜返回0"""
    color = board[y][x]
    if color == 0:
        return 0

    def count_dir(dx: int, dy: int) -> int:
        cx, cy = x + dx, y + dy
        c = 0
        while 0 <= cx < BOARD_SIZE and 0 <= cy < BOARD_SIZE and board[cy][cx] == color:
            c += 1
            cx += dx
            cy += dy
        return c

    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        total = 1 + count_dir(dx, dy) + count_dir(-dx, -dy)
        if total >= 5:
            return color
    return 0


class GomokuHandler(GameHandler):
    """五子棋游戏处理器"""

    @staticmethod
    def get_config() -> GameConfig:
        return GameConfig(
            game_name="gomoku",
            game_display_name="五子棋",
            team_size=1,  # 1v1
        )

    def create_game_state(self, team_a: list[str], team_b: list[str]) -> GomokuState:
        """创建五子棋游戏状态，随机分配黑白"""
        if not team_a or not team_b:
            raise ValueError("Both teams must have at least one player")
        
        # 五子棋是 1v1，取每方第一个玩家
        player_a = team_a[0]
        player_b = team_b[0]
        
        # 随机分配黑白
        if random.random() < 0.5:
            black, white = player_a, player_b
        else:
            black, white = player_b, player_a
        
        state = GomokuState.new(next_peer_id=black)
        state.colors = {black: 1, white: 2}
        return state

    def apply_action(self, state: Any, peer_id: str, action: dict[str, Any]) -> tuple[GomokuState, bool]:
        """应用落子操作"""
        if not isinstance(state, GomokuState):
            return state, False
        
        # 检查是否轮到该玩家
        if peer_id != state.next_peer_id:
            return state, False
        
        # 检查游戏是否已结束
        if state.winner_peer_id is not None:
            return state, False
        
        # 获取落子位置
        try:
            x = int(action.get("x", -1))
            y = int(action.get("y", -1))
        except (TypeError, ValueError):
            return state, False
        
        # 检查位置是否有效
        if not state.can_place(x, y):
            return state, False
        
        # 获取玩家颜色
        colors = state.colors or {}
        color = colors.get(peer_id)
        if color not in (1, 2):
            return state, False
        
        # 落子
        state.board[y][x] = color
        state.last_move = (x, y, color)
        
        # 检查是否获胜
        win_color = check_winner(state.board, x, y)
        if win_color:
            winner = next((pid for pid, c in colors.items() if c == win_color), None)
            state.winner_peer_id = winner
        else:
            # 切换到另一个玩家
            other = next((pid for pid, c in colors.items() if pid != peer_id), None)
            state.next_peer_id = other or peer_id
        
        return state, True

    def check_game_over(self, state: Any, team_a: list[str], team_b: list[str]) -> tuple[bool, str | None]:
        """检查游戏是否结束"""
        if not isinstance(state, GomokuState):
            return False, None
        
        if state.winner_peer_id is None:
            return False, None
        
        # 判断获胜方属于哪个队伍
        if state.winner_peer_id in team_a:
            return True, "team_a"
        elif state.winner_peer_id in team_b:
            return True, "team_b"
        else:
            return True, None

    def get_state_for_broadcast(self, state: Any) -> dict[str, Any]:
        """获取用于广播的状态"""
        if not isinstance(state, GomokuState):
            return {}
        
        colors = state.colors or {}
        black = next((pid for pid, c in colors.items() if c == 1), "")
        white = next((pid for pid, c in colors.items() if c == 2), "")
        
        return {
            "board": [cell for row in state.board for cell in row],  # 扁平化
            "next_peer_id": state.next_peer_id,
            "winner_peer_id": state.winner_peer_id,
            "last_move": list(state.last_move) if state.last_move else None,
            "black_peer_id": black,
            "white_peer_id": white,
            "board_size": BOARD_SIZE,
        }

    def get_next_player(self, state: Any) -> str | None:
        """获取下一个应该操作的玩家"""
        if not isinstance(state, GomokuState):
            return None
        if state.winner_peer_id is not None:
            return None
        return state.next_peer_id

    def get_winner(self, state: Any) -> str | None:
        """获取获胜玩家"""
        if not isinstance(state, GomokuState):
            return None
        return state.winner_peer_id


# 注册五子棋游戏
GameRegistry.register(GomokuHandler)
