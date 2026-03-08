"""游戏注册器 - 管理所有可用的游戏类型"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import GameConfig, GameHandler


class GameRegistry:
    """
    游戏注册器
    
    用于注册和获取各种游戏的处理器。新游戏只需实现 GameHandler 接口
    并调用 GameRegistry.register() 注册即可。
    """
    
    _handlers: dict[str, type["GameHandler"]] = {}

    @classmethod
    def register(cls, handler_class: type["GameHandler"]) -> None:
        """
        注册游戏处理器
        
        Args:
            handler_class: 实现了 GameHandler 接口的游戏处理器类
        """
        config = handler_class.get_config()
        cls._handlers[config.game_name] = handler_class

    @classmethod
    def get_handler(cls, game_name: str) -> "GameHandler | None":
        """
        获取游戏处理器实例
        
        Args:
            game_name: 游戏标识，如 "gomoku"
            
        Returns:
            GameHandler 实例，如果游戏未注册返回 None
        """
        handler_class = cls._handlers.get(game_name)
        return handler_class() if handler_class else None

    @classmethod
    def get_config(cls, game_name: str) -> "GameConfig | None":
        """
        获取游戏配置
        
        Args:
            game_name: 游戏标识
            
        Returns:
            GameConfig，如果游戏未注册返回 None
        """
        handler_class = cls._handlers.get(game_name)
        return handler_class.get_config() if handler_class else None

    @classmethod
    def get_all_games(cls) -> list["GameConfig"]:
        """
        获取所有已注册游戏的配置列表
        
        Returns:
            GameConfig 列表
        """
        return [h.get_config() for h in cls._handlers.values()]

    @classmethod
    def is_registered(cls, game_name: str) -> bool:
        """
        检查游戏是否已注册
        
        Args:
            game_name: 游戏标识
            
        Returns:
            是否已注册
        """
        return game_name in cls._handlers
