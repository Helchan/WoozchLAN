from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import Any

from .util import get_app_root, guess_local_ip, new_id, now_ms


# 昵称生成词库（3字形容词 + 2字名词 = 5字）
_NICKNAME_ADJECTIVES = [
    "爱睡的", "偷懒的", "快乐的", "勤奋的", "淡定的",
    "机智的", "呆萌的", "暴躁的", "佛系的", "社恐的",
    "内卷的", "躺平的", "摸鱼的", "划水的", "奋斗的",
    "安静的", "活泼的", "稳重的", "调皮的", "认真的",
    "努力的", "热情的", "冷静的", "可爱的", "帅气的",
    "温柔的", "霸气的", "低调的", "高冷的", "傲娇的",
]

_NICKNAME_NOUNS = [
    "小猫", "小狗", "熊猫", "企鹅", "兔子",
    "狐狸", "老虎", "狮子", "大象", "猴子",
    "海豚", "鲸鱼", "小鸟", "蝴蝶", "蜜蜂",
    "乌龟", "松鼠", "刺猬", "考拉", "袋鼠",
    "河马", "长颈", "斑马", "孔雀", "天鹅",
]


def generate_random_nickname() -> str:
    """生成随机昵称（形容词+名词，5个汉字）"""
    adj = random.choice(_NICKNAME_ADJECTIVES)
    noun = random.choice(_NICKNAME_NOUNS)
    return adj + noun


@dataclass
class LocalNode:
    """本机节点信息"""
    peer_id: str
    nickname: str
    ip: str
    udp_port: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "nickname": self.nickname,
            "ip": self.ip,
            "udp_port": self.udp_port,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalNode:
        return cls(
            peer_id=str(data.get("peer_id", "")).strip(),
            nickname=str(data.get("nickname", "")).strip(),
            ip=str(data.get("ip", "")).strip(),
            udp_port=int(data.get("udp_port", 37020) or 37020),
        )


@dataclass
class NetworkNode:
    """网络中的节点信息"""
    peer_id: str
    nickname: str
    ip: str
    udp_port: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "nickname": self.nickname,
            "ip": self.ip,
            "udp_port": self.udp_port,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkNode:
        return cls(
            peer_id=str(data.get("peer_id", "")).strip(),
            nickname=str(data.get("nickname", "")).strip(),
            ip=str(data.get("ip", "")).strip(),
            udp_port=int(data.get("udp_port", 37020) or 37020),
        )

    def key(self) -> str:
        return f"{self.ip}:{self.udp_port}"


def get_settings_path() -> str:
    """返回程序根目录下的 settings.json 路径"""
    return os.path.join(get_app_root(), "settings.json")


def load_settings() -> tuple[LocalNode | None, list[NetworkNode]]:
    """
    加载配置文件。
    返回 (local_node, network_nodes)，如果配置文件不存在或格式错误，local_node 为 None。
    """
    path = get_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None, []

    # 解析 local_node
    local_data = raw.get("local_node")
    local_node = None
    if isinstance(local_data, dict):
        peer_id = str(local_data.get("peer_id", "")).strip()
        nickname = str(local_data.get("nickname", "")).strip()
        if peer_id and nickname:
            local_node = LocalNode.from_dict(local_data)

    # 解析 network_nodes
    network_nodes: list[NetworkNode] = []
    nodes_data = raw.get("network_nodes", [])
    if isinstance(nodes_data, list):
        for item in nodes_data:
            if not isinstance(item, dict):
                continue
            peer_id = str(item.get("peer_id", "")).strip()
            ip = str(item.get("ip", "")).strip()
            udp_port = int(item.get("udp_port", 0) or 0)
            if peer_id and ip and udp_port > 0:
                network_nodes.append(NetworkNode.from_dict(item))

    return local_node, network_nodes


def save_settings(local_node: LocalNode, network_nodes: list[NetworkNode]) -> None:
    """保存配置到 settings.json"""
    path = get_settings_path()
    tmp = path + ".tmp"

    payload = {
        "local_node": local_node.to_dict(),
        "network_nodes": [n.to_dict() for n in network_nodes],
    }

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def init_local_node(current_ip: str, preferred_port: int = 37020) -> LocalNode:
    """
    初始化新用户的本机节点。
    生成新的 peer_id 和默认昵称。
    """
    peer_id = new_id()
    nickname = f"玩家{peer_id[:4].upper()}"
    return LocalNode(
        peer_id=peer_id,
        nickname=nickname,
        ip=current_ip,
        udp_port=preferred_port,
    )


def ensure_local_node_in_network(
    local_node: LocalNode, network_nodes: list[NetworkNode]
) -> list[NetworkNode]:
    """
    确保 local_node 在 network_nodes 中（根据 peer_id 匹配并更新）。
    返回更新后的 network_nodes 列表。
    """
    # 移除旧的本机节点（如果存在）
    filtered = [n for n in network_nodes if n.peer_id != local_node.peer_id]
    # 添加最新的本机节点信息
    filtered.insert(0, NetworkNode(
        peer_id=local_node.peer_id,
        nickname=local_node.nickname,
        ip=local_node.ip,
        udp_port=local_node.udp_port,
    ))
    return filtered


def update_network_node(
    network_nodes: list[NetworkNode], node: NetworkNode
) -> list[NetworkNode]:
    """
    更新或添加节点到 network_nodes 列表。
    如果 peer_id 已存在则更新，否则添加。
    """
    filtered = [n for n in network_nodes if n.peer_id != node.peer_id]
    filtered.append(node)
    return filtered


def remove_network_node(
    network_nodes: list[NetworkNode], peer_id: str
) -> list[NetworkNode]:
    """从 network_nodes 中移除指定 peer_id 的节点"""
    return [n for n in network_nodes if n.peer_id != peer_id]
