from __future__ import annotations

from dataclasses import dataclass


BOARD_SIZE = 15


@dataclass
class GameState:
    board: list[list[int]]
    next_peer_id: str
    winner_peer_id: str | None = None
    last_move: tuple[int, int, int] | None = None  # x,y,color

    @staticmethod
    def new(next_peer_id: str) -> "GameState":
        return GameState(board=[[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)], next_peer_id=next_peer_id)

    def can_place(self, x: int, y: int) -> bool:
        return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and self.board[y][x] == 0


def check_winner(board: list[list[int]], x: int, y: int) -> int:
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

