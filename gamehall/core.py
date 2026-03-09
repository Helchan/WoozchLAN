from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

from .game import GameRegistry
from .model.game import GameStateWrapper
from .model.room import RoomHostState, RoomSummary
from .net.node import Node, NodeConfig, NodeEvent
from .util import new_id, now_ms


@dataclass(frozen=True)
class CoreEvent:
    type: str
    payload: dict[str, Any]


class Core:
    def __init__(self, peer_id: str, nickname: str, on_event: Callable[[CoreEvent], None]) -> None:
        self._on_event = on_event

        self.node = Node(NodeConfig(peer_id=peer_id, nickname=nickname), on_event=self._on_node_event)
        self._lock = threading.Lock()

        self.rooms: dict[str, RoomSummary] = {}
        self._host_rooms: dict[str, RoomHostState] = {}
        self._active_room_id: str | None = None

        self._known_nicknames: dict[str, str] = {peer_id: nickname}

        # 使用 GameStateWrapper 管理游戏状态（通用化）
        self._games: dict[str, GameStateWrapper] = {}

        self._room_ad_thread: threading.Thread | None = None
        self._prune_thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def peer_id(self) -> str:
        return self.node.cfg.peer_id

    @property
    def nickname(self) -> str:
        return self.node.cfg.nickname

    def start(self) -> None:
        self.node.start()
        self._emit_peers()
        self._room_ad_thread = threading.Thread(target=self._room_ad_loop, name="room-ad", daemon=True)
        self._room_ad_thread.start()
        self._prune_thread = threading.Thread(target=self._prune_loop, name="room-prune", daemon=True)
        self._prune_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.node.stop()

    def set_nickname(self, nickname: str) -> None:
        nick = nickname.strip() or "玩家"
        if nick == self.nickname:
            return
        self._apply_nickname_update(self.peer_id, nick)
        self.node.update_nickname(nick)
        self._emit("nickname_changed", {"nickname": nick})
        self._emit_peers()

    def _apply_nickname_update(self, peer_id: str, nickname: str) -> None:
        nick = nickname.strip() or "玩家"
        host_room_ids: list[str] = []
        rooms_changed = False
        now = now_ms()
        with self._lock:
            self._known_nicknames[peer_id] = nick
            for rid, st in self._host_rooms.items():
                # 检查玩家是否在房间内
                if peer_id not in st.team_a and peer_id not in st.team_b and peer_id not in st.spectators:
                    continue
                st.nicknames[peer_id] = nick
                if peer_id == st.host_peer_id:
                    st.host_nickname = nick
                st.updated_ms = now
                host_room_ids.append(rid)
            for rid, summary in list(self.rooms.items()):
                changed = False
                updated = summary
                if summary.host_peer_id == peer_id and summary.host_nickname != nick:
                    updated = replace(updated, host_nickname=nick, updated_ms=max(updated.updated_ms, now))
                    changed = True
                if changed:
                    self.rooms[rid] = updated
                    rooms_changed = True
        for rid in host_room_ids:
            self._announce_room(rid)
            with self._lock:
                st = self._host_rooms.get(rid)
                parts = st.participants() if st is not None else None
            if parts is not None:
                self._broadcast_room(rid, {"type": "room_state", "room_id": rid, "participants": parts})
                self._emit("room_state", {"room_id": rid, "participants": parts})
        if rooms_changed:
            self._emit("rooms", {})

    def create_room(self, name: str, game: str = "gobang") -> str:
        assert self.node.listen_addr is not None
        room_id = f"{self.peer_id[:8]}-{new_id()[:10]}"
        game_key = game.strip().lower() if isinstance(game, str) else "gobang"
        
        # 从 GameRegistry 获取游戏配置
        handler = GameRegistry.get_handler(game_key)
        if handler is None:
            game_key = "gobang"
            handler = GameRegistry.get_handler(game_key)
        config = handler.get_config() if handler else None
        team_size = config.team_size if config else 1
        
        st = RoomHostState(
            room_id=room_id,
            name=name.strip() or "房间",
            host_peer_id=self.peer_id,
            host_nickname=self.nickname,
            host_ip=self.node.local_ip,
            host_port=self.node.listen_addr.port,
            game=game_key,
            team_size=team_size,
            created_ms=now_ms(),
            updated_ms=now_ms(),
        )
        st.nicknames[self.peer_id] = self.nickname
        with self._lock:
            self._host_rooms[room_id] = st
            self._active_room_id = room_id
        self._upsert_room(st.summary())
        self._emit("room_entered", {"room_id": room_id, "role": "host", "participants": st.participants()})
        return room_id

    def join_room(self, room_id: str, want: str) -> None:
        with self._lock:
            room = self.rooms.get(room_id)
        if room is None:
            return
        self.node.send_to_peer(
            room.host_peer_id,
            {
                "type": "room_join",
                "room_id": room_id,
                "want": want,
                "peer_id": self.peer_id,
                "nickname": self.nickname,
            },
        )

    def leave_room(self, room_id: str) -> None:
        with self._lock:
            is_host = room_id in self._host_rooms
            room = self.rooms.get(room_id)
            if self._active_room_id == room_id:
                self._active_room_id = None

        if is_host:
            self._close_host_room(room_id)
            return

        if room is not None:
            self.node.send_to_peer(room.host_peer_id, {"type": "room_leave", "room_id": room_id, "peer_id": self.peer_id})
        self._emit("room_left", {"room_id": room_id})

    def set_ready(self, room_id: str, ready: bool) -> None:
        with self._lock:
            room = self.rooms.get(room_id)
            is_host = room_id in self._host_rooms
        if is_host:
            return
        if room is None:
            return
        self.node.send_to_peer(
            room.host_peer_id,
            {"type": "room_ready", "room_id": room_id, "peer_id": self.peer_id, "ready": bool(ready)},
        )

    def start_game(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return

        # 使用新的 can_start_game 方法检查
        if not st.can_start_game():
            return

        st.status = "playing"
        st.updated_ms = now_ms()
        self._announce_room(room_id)

        # 使用 GameHandler 创建游戏状态
        handler = GameRegistry.get_handler(st.game)
        if handler is None:
            return
        
        game_state = handler.create_game_state(st.team_a, st.team_b)
        
        # 使用 GameStateWrapper 包装游戏状态
        wrapper = GameStateWrapper(
            game_name=st.game,
            state=game_state,
            started_ms=now_ms(),
        )
        with self._lock:
            self._games[room_id] = wrapper

        # 广播游戏开始（通用格式）
        broadcast_state = handler.get_state_for_broadcast(game_state)
        self._broadcast_room(room_id, {
            "type": "game_start",
            "room_id": room_id,
            "game": st.game,
            "game_state": broadcast_state,
            # 保留向后兼容字段
            "black_peer_id": broadcast_state.get("black_peer_id"),
            "white_peer_id": broadcast_state.get("white_peer_id"),
            "board_size": broadcast_state.get("board_size", 15),
            "next_peer_id": broadcast_state.get("next_peer_id"),
        })
        self._broadcast_game_state(room_id)
        self._emit("game_started", {
            "room_id": room_id,
            "game": st.game,
            "black_peer_id": broadcast_state.get("black_peer_id"),
            "white_peer_id": broadcast_state.get("white_peer_id"),
            "next_peer_id": broadcast_state.get("next_peer_id"),
        })

    def reset_game(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        if not st.team_b:
            return
        st.status = "waiting"
        # 重置 B 方所有成员的准备状态
        for pid in st.team_b:
            st.ready[pid] = False
        st.updated_ms = now_ms()
        with self._lock:
            self._games.pop(room_id, None)
        self._announce_room(room_id)
        parts = st.participants()
        self._broadcast_room(room_id, {"type": "room_state", "room_id": room_id, "participants": parts})
        self._emit("room_state", {"room_id": room_id, "participants": parts})
        self._broadcast_room(room_id, {"type": "game_reset", "room_id": room_id})
        self._emit("toast", {"text": "已重置棋盘，可重新准备开局"})

    def play_move(self, room_id: str, x: int, y: int) -> None:
        with self._lock:
            is_host = room_id in self._host_rooms
            room = self.rooms.get(room_id)
        if is_host:
            self._apply_move_as_host(room_id, self.peer_id, x, y)
            return
        if room is None:
            return
        self.node.send_to_peer(room.host_peer_id, {"type": "game_move", "room_id": room_id, "peer_id": self.peer_id, "x": x, "y": y})

    def send_chat(self, room_id: str, text: str) -> None:
        t = (text or "").strip()
        if not room_id or not t:
            return
        with self._lock:
            is_host = room_id in self._host_rooms
            room = self.rooms.get(room_id)
        msg = {"type": "room_chat", "room_id": room_id, "peer_id": self.peer_id, "nickname": self.nickname, "text": t}
        if is_host:
            self._handle_room_chat(msg)
            return
        if room is None:
            return
        self.node.send_to_peer(room.host_peer_id, msg)

    def _emit_peers(self) -> None:
        peers = [
            {
                "peer_id": self.peer_id,
                "nickname": self.nickname,
                "ip": self.node.local_ip,
                "port": (self.node.listen_addr.port if self.node.listen_addr is not None else 0),
                "last_seen_ms": now_ms(),
            }
        ]
        peers.extend(
            [
                {
                    "peer_id": p.peer_id,
                    "nickname": p.nickname,
                    "ip": p.ip,
                    "port": p.port,
                    "last_seen_ms": p.last_seen_ms,
                }
                for p in self.node.peers_snapshot()
                if p.peer_id != self.peer_id
            ]
        )
        with self._lock:
            for p in peers:
                pid = str(p.get("peer_id", ""))
                nick = str(p.get("nickname", ""))
                if pid and nick:
                    self._known_nicknames[pid] = nick
        self._emit("peers", {"items": peers})

    def _on_node_event(self, ev: NodeEvent) -> None:
        if ev.type == "node_started":
            self._emit("node", ev.payload)
            self._emit_peers()
            return
        if ev.type == "peers_changed":
            self._emit_peers()
            return
        if ev.type == "net_message":
            msg = ev.payload.get("message")
            if isinstance(msg, dict):
                self._handle_message(msg)
            return

    def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "nickname_update":
            peer_id = str(msg.get("peer_id", ""))
            nickname = str(msg.get("nickname", ""))
            if peer_id and nickname:
                self._apply_nickname_update(peer_id, nickname)
            return
        if mtype == "room_announce":
            room = msg.get("room")
            if isinstance(room, dict):
                self._handle_room_announce(room)
            return
        if mtype == "room_close":
            room_id = str(msg.get("room_id", ""))
            message = str(msg.get("message", "")) or "房间已关闭"
            if room_id:
                with self._lock:
                    self.rooms.pop(room_id, None)
                self._emit("rooms", {})
                if self._active_room_id == room_id:
                    self._active_room_id = None
                    # 显示弹窗提醒，然后返回大厅
                    self._emit("room_closed_alert", {"room_id": room_id, "message": message})
            return
        if mtype == "room_join":
            self._handle_room_join(msg)
            return
        if mtype == "room_join_result":
            self._handle_room_join_result(msg)
            return
        if mtype == "room_leave":
            self._handle_room_leave(msg)
            return
        if mtype == "room_ready":
            self._handle_room_ready(msg)
            return
        if mtype == "room_state":
            room_id = str(msg.get("room_id", ""))
            if room_id:
                self._emit("room_state", {"room_id": room_id, "participants": msg.get("participants")})
            return
        if mtype == "room_chat":
            self._handle_room_chat(msg)
            return
        if mtype == "game_start":
            self._handle_game_start(msg)
            return
        if mtype == "game_state":
            self._handle_game_state(msg)
            return
        if mtype == "game_move":
            self._handle_game_move(msg)
            return
        if mtype == "game_reset":
            room_id = str(msg.get("room_id", ""))
            if room_id:
                with self._lock:
                    self._games.pop(room_id, None)
                self._emit("game_state", {"room_id": room_id})
            return

    def _handle_room_announce(self, room: dict[str, Any]) -> None:
        try:
            summary = RoomSummary(
                room_id=str(room.get("room_id", "")),
                name=str(room.get("name", "房间")),
                host_peer_id=str(room.get("host_peer_id", "")),
                host_nickname=str(room.get("host_nickname", "")) or "房主",
                host_ip=str(room.get("host_ip", "")),
                host_port=int(room.get("host_port", 0) or 0),
                status=str(room.get("status", "waiting")),
                team_a_count=int(room.get("team_a_count", 1) or 1),
                team_b_count=int(room.get("team_b_count", 0) or 0),
                team_size=int(room.get("team_size", 1) or 1),
                players=int(room.get("players", 1) or 1),
                spectators=int(room.get("spectators", 0) or 0),
                updated_ms=int(room.get("updated_ms", 0) or 0),
                game=str(room.get("game", "gobang") or "gobang"),
            )
        except Exception:
            return
        if not summary.room_id or not summary.host_peer_id:
            return
        if summary.host_peer_id == self.peer_id:
            return
        with self._lock:
            if summary.host_peer_id and summary.host_nickname:
                self._known_nicknames[summary.host_peer_id] = summary.host_nickname
        self._upsert_room(summary)

    def _upsert_room(self, summary: RoomSummary) -> None:
        changed = False
        with self._lock:
            old = self.rooms.get(summary.room_id)
            if old is None or old.updated_ms < summary.updated_ms:
                self.rooms[summary.room_id] = summary
                changed = True
        if changed:
            self._emit("rooms", {})

    def _handle_room_join(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        peer_id = str(msg.get("peer_id", ""))
        want = str(msg.get("want", "watch"))
        nickname = str(msg.get("nickname", "")) or "玩家"
        if not room_id or not peer_id:
            return
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return

        st.nicknames[peer_id] = nickname
        with self._lock:
            self._known_nicknames[peer_id] = nickname

        role = "spectator"
        ok = True
        reason = ""
        if want == "play":
            if st.status != "waiting":
                ok = False
                reason = "对战中仅可观战"
            elif st.is_team_b_full():
                ok = False
                reason = "房间已满"
            else:
                # 加入 B 方
                if peer_id not in st.team_b:
                    st.team_b.append(peer_id)
                role = "player2"
                st.ready.setdefault(peer_id, False)
        else:
            if st.status == "waiting" and not st.is_team_b_full():
                ok = False
                reason = "缺人时只能加入对战"
            else:
                st.spectators.add(peer_id)

        st.updated_ms = now_ms()
        self._announce_room(room_id)
        self._emit("room_state", {"room_id": room_id, "participants": st.participants()})

        self.node.send_to_peer(
            peer_id,
            {
                "type": "room_join_result",
                "room_id": room_id,
                "ok": ok,
                "role": (role if ok else "rejected"),
                "reason": reason,
                "status": st.status,
                "participants": st.participants(),
            },
        )

        if ok and role == "spectator" and st.status == "playing":
            with self._lock:
                wrapper = self._games.get(room_id)
            if wrapper and st.team_b:
                game_state = wrapper.state
                # 从游戏状态中获取 colors
                colors = getattr(game_state, 'colors', {}) or {}
                black = next((pid for pid, c in colors.items() if c == 1), st.host_peer_id)
                white = next((pid for pid, c in colors.items() if c == 2), st.team_b[0] if st.team_b else "")
                
                # 获取广播状态
                handler = GameRegistry.get_handler(st.game)
                if handler:
                    broadcast_state = handler.get_state_for_broadcast(game_state)
                    board_size = broadcast_state.get("board_size", 15)
                    self.node.send_to_peer(
                        peer_id,
                        {
                            "type": "game_start",
                            "room_id": room_id,
                            "game": st.game,
                            "game_state": broadcast_state,
                            "black_peer_id": black,
                            "white_peer_id": white,
                            "board_size": board_size,
                            "next_peer_id": getattr(game_state, 'next_peer_id', black),
                        },
                    )
                    self.node.send_to_peer(
                        peer_id,
                        {
                            "type": "game_state",
                            "room_id": room_id,
                            "game": st.game,
                            "game_state": broadcast_state,
                            "board": broadcast_state.get("board", []),
                            "next_peer_id": broadcast_state.get("next_peer_id"),
                            "winner_peer_id": broadcast_state.get("winner_peer_id"),
                            "last_move": broadcast_state.get("last_move"),
                        },
                    )

    def _handle_room_join_result(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        ok = bool(msg.get("ok", False))
        if not room_id:
            return
        if not ok:
            self._emit("toast", {"text": str(msg.get("reason", "无法加入房间"))})
            return
        role = str(msg.get("role", "spectator"))
        status = str(msg.get("status", ""))
        
        # 如果房间状态是 waiting，清理本地游戏状态（防止显示旧棋盘）
        if status == "waiting":
            with self._lock:
                self._games.pop(room_id, None)
        
        with self._lock:
            self._active_room_id = room_id
        payload: dict[str, Any] = {"room_id": room_id, "role": role, "participants": msg.get("participants")}
        if status:
            payload["status"] = status
        self._emit("room_entered", payload)

    def _handle_room_leave(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        peer_id = str(msg.get("peer_id", ""))
        if not room_id or not peer_id:
            return
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return

        was_in_team_b = peer_id in st.team_b
        was_playing = st.status == "playing"
        left_nickname = st.nicknames.get(peer_id, peer_id[:6])

        # 使用 RoomHostState 的 remove_player 方法
        st.remove_player(peer_id)

        # 检查 B 方是否全部退出
        team_b_empty = len(st.team_b) == 0
        should_show_alert = False
        alert_message = ""
        
        if was_in_team_b and team_b_empty:
            # 如果对战中，重置游戏状态
            if was_playing:
                st.status = "waiting"
                with self._lock:
                    self._games.pop(room_id, None)
                should_show_alert = True
                alert_message = f"对手 {left_nickname} 已退出，游戏结束"
            else:
                # 等待中，B 方全部退出
                self._emit("toast", {"text": f"玩家 {left_nickname} 已退出"})

        st.updated_ms = now_ms()
        self._announce_room(room_id)

        # 先广播新的房间状态（确保 participants 更新）
        parts = st.participants()
        self._broadcast_room(room_id, {"type": "room_state", "room_id": room_id, "participants": parts})
        self._emit("room_state", {"room_id": room_id, "participants": parts})
        
        # 然后再显示弹窗和刷新游戏状态
        if should_show_alert:
            self._emit("game_state", {"room_id": room_id})  # 触发 UI 刷新
            self._emit("opponent_left_alert", {
                "room_id": room_id,
                "message": alert_message,
            })

    def _handle_room_ready(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        peer_id = str(msg.get("peer_id", ""))
        ready = bool(msg.get("ready", False))
        if not room_id or not peer_id:
            return
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        # 只有 B 方成员可以准备
        if peer_id not in st.team_b:
            return
        st.ready[peer_id] = ready
        st.updated_ms = now_ms()
        self._announce_room(room_id)
        self._broadcast_room(room_id, {"type": "room_state", "room_id": room_id, "participants": st.participants()})
        self._emit("room_state", {"room_id": room_id, "participants": st.participants()})

    def _handle_game_move(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        peer_id = str(msg.get("peer_id", ""))
        try:
            x = int(msg.get("x", -1))
            y = int(msg.get("y", -1))
        except Exception:
            return
        if not room_id or not peer_id:
            return
        with self._lock:
            if room_id not in self._host_rooms:
                return
        self._apply_move_as_host(room_id, peer_id, x, y)

    def _apply_move_as_host(self, room_id: str, peer_id: str, x: int, y: int) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
            wrapper = self._games.get(room_id)
        if st is None or wrapper is None:
            return
        if st.status != "playing":
            return
        
        game_state = wrapper.state
        
        # 使用 GameHandler 处理操作
        handler = GameRegistry.get_handler(st.game)
        if handler is None:
            return
        
        # 检查游戏是否已结束
        game_over, _ = handler.check_game_over(game_state, st.team_a, st.team_b)
        if game_over:
            return
        
        # 应用操作
        action = {"x": x, "y": y}
        new_state, success = handler.apply_action(game_state, peer_id, action)
        if not success:
            return
        
        # 更新 wrapper 中的状态
        wrapper.update_state(new_state, now_ms())
        
        # 检查游戏是否结束
        game_over, winner_team = handler.check_game_over(new_state, st.team_a, st.team_b)
        if game_over:
            st.status = "waiting"
            # 重置 B 方准备状态
            for pid in st.team_b:
                st.ready[pid] = False
            st.updated_ms = now_ms()
            self._announce_room(room_id)
            parts = st.participants()
            self._broadcast_room(room_id, {"type": "room_state", "room_id": room_id, "participants": parts})
            self._emit("room_state", {"room_id": room_id, "participants": parts})
        
        self._broadcast_game_state(room_id)

    def _handle_game_start(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        if not room_id:
            return
        
        # 获取游戏类型和状态数据
        game_name = str(msg.get("game", "gobang"))
        game_data = msg.get("game_state", {})
        
        # 使用 GameHandler 恢复游戏状态
        handler = GameRegistry.get_handler(game_name)
        if handler is None:
            # 回退到默认处理（向后兼容）
            game_name = "gobang"
            handler = GameRegistry.get_handler(game_name)
        
        if handler is None:
            return
        
        # 从广播数据恢复游戏状态
        if game_data:
            game_state = handler.restore_from_broadcast(game_data)
        else:
            # 向后兼容：从旧格式字段恢复
            black = str(msg.get("black_peer_id", ""))
            white = str(msg.get("white_peer_id", ""))
            next_peer_id = str(msg.get("next_peer_id", black))
            board_size = int(msg.get("board_size", 15))
            game_state = handler.restore_from_broadcast({
                "black_peer_id": black,
                "white_peer_id": white,
                "next_peer_id": next_peer_id,
                "board_size": board_size,
                "board": [0] * (board_size * board_size),
                "colors": {black: 1, white: 2} if black and white else {},
            })
        
        # 使用 GameStateWrapper 包装
        wrapper = GameStateWrapper(
            game_name=game_name,
            state=game_state,
            started_ms=now_ms(),
        )
        with self._lock:
            self._games[room_id] = wrapper
        
        # 获取广播状态中的字段用于事件
        broadcast_state = handler.get_state_for_broadcast(game_state)
        self._emit("game_started", {
            "room_id": room_id,
            "game": game_name,
            "black_peer_id": broadcast_state.get("black_peer_id", ""),
            "white_peer_id": broadcast_state.get("white_peer_id", ""),
            "next_peer_id": broadcast_state.get("next_peer_id", ""),
        })

    def _handle_room_chat(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        peer_id = str(msg.get("peer_id", ""))
        nickname = str(msg.get("nickname", "")) or self._known_nicknames.get(peer_id, "玩家")
        text = str(msg.get("text", "")).strip()
        if not room_id or not peer_id or not text:
            return

        with self._lock:
            st = self._host_rooms.get(room_id)
            room = self.rooms.get(room_id)

        if st is not None:
            allowed = peer_id in st.team_a or peer_id in st.team_b or peer_id in st.spectators
            if not allowed:
                return
            st.nicknames[peer_id] = nickname
            with self._lock:
                self._known_nicknames[peer_id] = nickname
            self._broadcast_room(room_id, {"type": "room_chat", "room_id": room_id, "peer_id": peer_id, "nickname": nickname, "text": text})

        elif room is not None:
            pass
        else:
            return

        self._emit("chat", {"room_id": room_id, "peer_id": peer_id, "nickname": nickname, "text": text})

    def _broadcast_game_state(self, room_id: str) -> None:
        with self._lock:
            wrapper = self._games.get(room_id)
            st = self._host_rooms.get(room_id)
        if wrapper is None:
            return
        
        game_state = wrapper.state
        
        # 使用 GameHandler 获取广播状态
        game_name = st.game if st else wrapper.game_name
        handler = GameRegistry.get_handler(game_name)
        if handler is None:
            return
        
        broadcast_state = handler.get_state_for_broadcast(game_state)
        self._broadcast_room(
            room_id,
            {
                "type": "game_state",
                "room_id": room_id,
                "game": game_name,
                "game_state": broadcast_state,
                # 保留向后兼容字段
                "board": broadcast_state.get("board", []),
                "next_peer_id": broadcast_state.get("next_peer_id"),
                "winner_peer_id": broadcast_state.get("winner_peer_id"),
                "last_move": broadcast_state.get("last_move"),
            },
        )
        self._emit("game_state", {"room_id": room_id})

    def _handle_game_state(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        if not room_id:
            return
        
        # 获取游戏类型
        game_name = str(msg.get("game", "gobang"))
        game_data = msg.get("game_state", {})
        
        # 使用 GameHandler 恢复游戏状态
        handler = GameRegistry.get_handler(game_name)
        if handler is None:
            game_name = "gobang"
            handler = GameRegistry.get_handler(game_name)
        
        if handler is None:
            return
        
        # 从广播数据恢复游戏状态
        if game_data:
            game_state = handler.restore_from_broadcast(game_data)
        else:
            # 向后兼容：从旧格式字段恢复
            board = msg.get("board", [])
            game_state = handler.restore_from_broadcast({
                "board": board,
                "next_peer_id": str(msg.get("next_peer_id", "")),
                "winner_peer_id": msg.get("winner_peer_id"),
                "last_move": msg.get("last_move"),
                "board_size": 15,
            })
        
        # 使用 GameStateWrapper 包装
        wrapper = GameStateWrapper(
            game_name=game_name,
            state=game_state,
            last_action_ms=now_ms(),
        )
        with self._lock:
            self._games[room_id] = wrapper
        self._emit("game_state", {"room_id": room_id})

    def _room_ad_loop(self) -> None:
        while not self._stop.is_set():
            ids: list[str]
            with self._lock:
                ids = list(self._host_rooms.keys())
            for rid in ids:
                self._announce_room(rid)
            self._stop.wait(1.0)

    def _announce_room(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        st.host_nickname = self._known_nicknames.get(st.host_peer_id, st.host_nickname) or st.host_nickname
        summary = st.summary()
        self._upsert_room(summary)
        self.node.broadcast({"type": "room_announce", "room": summary.__dict__})

    def _broadcast_room(self, room_id: str, msg: dict[str, Any]) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        # 收集所有参与者
        targets = list(st.team_a) + list(st.team_b) + list(st.spectators)
        for pid in targets:
            if pid == self.peer_id:
                continue
            self.node.send_to_peer(pid, msg)

    def _close_host_room(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            with self._lock:
                self._host_rooms.pop(room_id, None)
                self.rooms.pop(room_id, None)
                self._games.pop(room_id, None)
            self._emit("rooms", {})
            self._emit("room_left", {"room_id": room_id, "host_closed": True})
            return

        # 通知房间内所有人（B方玩家和观战者）房间已关闭
        targets = list(st.team_b) + list(st.spectators)

        for pid in targets:
            self.node.send_to_peer(pid, {
                "type": "room_close",
                "room_id": room_id,
                "reason": "host_left",
                "message": f"房主 {st.host_nickname} 已退出，房间已关闭",
            })

        # 广播房间关闭消息给所有在线玩家（让他们从房间列表中移除该房间）
        self.node.broadcast({
            "type": "room_close",
            "room_id": room_id,
            "reason": "host_left",
            "message": f"房主 {st.host_nickname} 已退出，房间已关闭",
        })

        # 清理本地房间数据
        with self._lock:
            self._host_rooms.pop(room_id, None)
            self.rooms.pop(room_id, None)
            self._games.pop(room_id, None)
        self._emit("rooms", {})
        self._emit("room_left", {"room_id": room_id, "host_closed": True})

    def _prune_loop(self) -> None:
        while not self._stop.is_set():
            self._prune_rooms()
            self._stop.wait(2.0)

    def _prune_rooms(self) -> None:
        cutoff = now_ms() - 8_000
        peers = {p.peer_id for p in self.node.peers_snapshot()}
        removed: list[str] = []
        changed_host_rooms: list[tuple[str, dict[str, object]]] = []
        game_reset_rooms: list[str] = []
        opponent_left_alerts: list[tuple[str, str]] = []  # (room_id, nickname)
        with self._lock:
            for rid, r in list(self.rooms.items()):
                if r.host_peer_id == self.peer_id:
                    continue
                if r.updated_ms < cutoff and r.host_peer_id not in peers:
                    removed.append(rid)
                    del self.rooms[rid]
            for rid, st in list(self._host_rooms.items()):
                dirty = False
                # 处理 B 方玩家离线
                stale_team_b = [pid for pid in st.team_b if pid not in peers]
                for pid in stale_team_b:
                    old_nickname = st.nicknames.get(pid, pid[:6])
                    st.remove_player(pid)
                    dirty = True
                
                # 检查 B 方是否全部离线
                if stale_team_b and len(st.team_b) == 0:
                    # 如果游戏进行中，需要重置游戏
                    if st.status == "playing":
                        st.status = "waiting"
                        game_reset_rooms.append(rid)
                        # 记录需要通知房主的信息
                        opponent_left_alerts.append((rid, old_nickname))

                # 处理观战者离线
                stale_specs = [s for s in st.spectators if s not in peers]
                for s in stale_specs:
                    st.spectators.discard(s)
                    st.ready.pop(s, None)
                    st.nicknames.pop(s, None)
                if stale_specs:
                    dirty = True
                if dirty:
                    st.updated_ms = now_ms()
                    changed_host_rooms.append((rid, st.participants()))

        # 清理游戏状态
        for rid in game_reset_rooms:
            with self._lock:
                self._games.pop(rid, None)

        if removed:
            self._emit("rooms", {})
        
        # 先广播房间状态（确保 participants 更新）
        for rid, parts in changed_host_rooms:
            self._announce_room(rid)
            self._broadcast_room(rid, {"type": "room_state", "room_id": rid, "participants": parts})
            self._emit("room_state", {"room_id": rid, "participants": parts})
        
        # 然后刷新游戏状态和显示弹窗
        for rid in game_reset_rooms:
            self._emit("game_state", {"room_id": rid})
        
        # 最后发送弹窗提示
        for rid, nickname in opponent_left_alerts:
            self._emit("opponent_left_alert", {
                "room_id": rid,
                "message": f"对手 {nickname} 已离线，游戏结束",
            })

    def _emit(self, etype: str, payload: dict[str, Any]) -> None:
        try:
            self._on_event(CoreEvent(type=etype, payload=payload))
        except Exception:
            pass
