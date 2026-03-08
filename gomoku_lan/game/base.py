"""游戏处理器基类定义"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GameConfig:
    """游戏配置信息"""
    game_name: str  # 游戏标识，如 "gomoku"
    game_display_name: str  # 显示名称，如 "五子棋"
    team_size: int = 1  # 每方人数，1v1 则为 1，2v2 则为 2


class GameHandler(ABC):
    """
    游戏处理器抽象基类
    
    每种游戏需要实现此接口，处理游戏特定的逻辑：
    - 游戏状态初始化
    - 玩家操作处理
    - 胜负判定
    - 状态广播
    """

    @staticmethod
    @abstractmethod
    def get_config() -> GameConfig:
        """
        返回游戏配置
        
        Returns:
            GameConfig: 包含游戏名称、显示名称、每方人数等配置
        """
        pass

    @abstractmethod
    def create_game_state(self, team_a: list[str], team_b: list[str]) -> Any:
        """
        创建游戏初始状态
        
        Args:
            team_a: A方玩家 peer_id 列表（通常包含房主）
            team_b: B方玩家 peer_id 列表
            
        Returns:
            游戏状态对象，类型由具体游戏定义
        """
        pass

    @abstractmethod
    def apply_action(self, state: Any, peer_id: str, action: dict[str, Any]) -> tuple[Any, bool]:
        """
        应用玩家操作
        
        Args:
            state: 当前游戏状态
            peer_id: 执行操作的玩家 peer_id
            action: 操作内容，如 {"type": "move", "x": 7, "y": 7}
            
        Returns:
            (新状态, 是否成功): 如果操作无效返回 (原状态, False)
        """
        pass

    @abstractmethod
    def check_game_over(self, state: Any, team_a: list[str], team_b: list[str]) -> tuple[bool, str | None]:
        """
        检查游戏是否结束
        
        Args:
            state: 当前游戏状态
            team_a: A方玩家列表
            team_b: B方玩家列表
            
        Returns:
            (是否结束, 获胜方): 获胜方为 "team_a" | "team_b" | None（平局或未结束）
        """
        pass

    @abstractmethod
    def get_state_for_broadcast(self, state: Any) -> dict[str, Any]:
        """
        获取用于网络广播的游戏状态
        
        Args:
            state: 当前游戏状态
            
        Returns:
            可序列化为 JSON 的状态字典
        """
        pass

    @abstractmethod
    def get_next_player(self, state: Any) -> str | None:
        """
        获取下一个应该操作的玩家
        
        Args:
            state: 当前游戏状态
            
        Returns:
            下一个玩家的 peer_id，如果游戏已结束返回 None
        """
        pass

    @abstractmethod
    def get_winner(self, state: Any) -> str | None:
        """
        获取获胜玩家的 peer_id
        
        Args:
            state: 当前游戏状态
            
        Returns:
            获胜玩家的 peer_id，如果未结束或平局返回 None
        """
        pass
