"""游戏抽象层 - 提供统一的游戏处理器接口"""

from .base import GameConfig, GameHandler
from .registry import GameRegistry
from .gomoku import GomokuHandler, GomokuState, BOARD_SIZE

__all__ = ["GameConfig", "GameHandler", "GameRegistry", "GomokuHandler", "GomokuState", "BOARD_SIZE"]
