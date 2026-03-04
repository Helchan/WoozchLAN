from __future__ import annotations

import threading
from dataclasses import dataclass
import random
from typing import Any, Callable

from .model.game import BOARD_SIZE, GameState, check_winner
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

        self._games: dict[str, GameState] = {}
        self._colors: dict[str, dict[str, int]] = {}

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
        self._room_ad_thread = threading.Thread(target=self._room_ad_loop, name="room-ad", daemon=True)
        self._room_ad_thread.start()
        self._prune_thread = threading.Thread(target=self._prune_loop, name="room-prune", daemon=True)
        self._prune_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.node.stop()

    def set_nickname(self, nickname: str) -> None:
        nick = nickname.strip() or "玩家"
        with self._lock:
            self._known_nicknames[self.peer_id] = nick
        self.node.update_nickname(nick)
        self._emit("nickname_changed", {"nickname": nick})

    def create_room(self, name: str) -> str:
        assert self.node.listen_addr is not None
        room_id = f"{self.peer_id[:8]}-{new_id()[:10]}"
        st = RoomHostState(
            room_id=room_id,
            name=name.strip() or "房间",
            host_peer_id=self.peer_id,
            host_nickname=self.nickname,
            host_ip=self.node.local_ip,
            host_port=self.node.listen_addr.port,
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

        if not st.player2_peer_id:
            return
        if not st.ready.get(st.player2_peer_id):
            return

        st.status = "playing"
        st.updated_ms = now_ms()
        self._announce_room(room_id)

        host = st.host_peer_id
        p2 = st.player2_peer_id
        black, white = (host, p2) if random.random() < 0.5 else (p2, host)
        game = GameState.new(next_peer_id=black)
        with self._lock:
            self._games[room_id] = game
            self._colors[room_id] = {black: 1, white: 2}

        self._broadcast_room(room_id, {"type": "game_start", "room_id": room_id, "black_peer_id": black, "white_peer_id": white, "board_size": BOARD_SIZE, "next_peer_id": game.next_peer_id})
        self._broadcast_game_state(room_id)
        self._emit("game_started", {"room_id": room_id, "black_peer_id": black, "white_peer_id": white, "next_peer_id": game.next_peer_id})

    def reset_game(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        if not st.player2_peer_id:
            return
        st.status = "waiting"
        st.ready[st.player2_peer_id] = False
        st.updated_ms = now_ms()
        with self._lock:
            self._games.pop(room_id, None)
            self._colors.pop(room_id, None)
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

    def _on_node_event(self, ev: NodeEvent) -> None:
        if ev.type == "node_started":
            self._emit("node", ev.payload)
            return
        if ev.type == "peers_changed":
            peers = [
                {"peer_id": p.peer_id, "nickname": p.nickname, "ip": p.ip, "port": p.port, "last_seen_ms": p.last_seen_ms}
                for p in self.node.peers_snapshot()
            ]
            with self._lock:
                for p in peers:
                    pid = str(p.get("peer_id", ""))
                    nick = str(p.get("nickname", ""))
                    if pid and nick:
                        self._known_nicknames[pid] = nick
            self._emit("peers", {"items": peers})
            return
        if ev.type == "net_message":
            msg = ev.payload.get("message")
            if isinstance(msg, dict):
                self._handle_message(msg)
            return

    def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "room_announce":
            room = msg.get("room")
            if isinstance(room, dict):
                self._handle_room_announce(room)
            return
        if mtype == "room_close":
            room_id = str(msg.get("room_id", ""))
            if room_id:
                with self._lock:
                    self.rooms.pop(room_id, None)
                self._emit("rooms", {})
                if self._active_room_id == room_id:
                    self._active_room_id = None
                    self._emit("room_left", {"room_id": room_id, "forced": True})
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
                    self._colors.pop(room_id, None)
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
                player2_peer_id=(str(room.get("player2_peer_id")) if room.get("player2_peer_id") else None),
                player2_nickname=(str(room.get("player2_nickname")) if room.get("player2_nickname") else None),
                players=int(room.get("players", 1) or 1),
                spectators=int(room.get("spectators", 0) or 0),
                updated_ms=int(room.get("updated_ms", 0) or 0),
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
            if summary.player2_peer_id and summary.player2_nickname:
                self._known_nicknames[summary.player2_peer_id] = summary.player2_nickname
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
            elif st.player2_peer_id and st.player2_peer_id != peer_id:
                ok = False
                reason = "房间已满"
            else:
                st.player2_peer_id = peer_id
                st.player2_nickname = nickname
                role = "player2"
                st.ready.setdefault(peer_id, False)
        else:
            if st.status == "waiting" and not st.player2_peer_id:
                ok = False
                reason = "二缺一时只能加入对战"
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
                colors = self._colors.get(room_id)
                game = self._games.get(room_id)
            if colors and game and st.player2_peer_id:
                black = st.host_peer_id
                white = st.player2_peer_id
                self.node.send_to_peer(
                    peer_id,
                    {
                        "type": "game_start",
                        "room_id": room_id,
                        "black_peer_id": black,
                        "white_peer_id": white,
                        "board_size": BOARD_SIZE,
                        "next_peer_id": game.next_peer_id,
                    },
                )
                flat = [cell for row in game.board for cell in row]
                self.node.send_to_peer(
                    peer_id,
                    {
                        "type": "game_state",
                        "room_id": room_id,
                        "board": flat,
                        "next_peer_id": game.next_peer_id,
                        "winner_peer_id": game.winner_peer_id,
                        "last_move": list(game.last_move) if game.last_move else None,
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
        if peer_id == st.player2_peer_id:
            st.player2_peer_id = None
            st.player2_nickname = None
        st.spectators.discard(peer_id)
        st.ready.pop(peer_id, None)
        st.nicknames.pop(peer_id, None)
        st.updated_ms = now_ms()
        self._announce_room(room_id)

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
        if peer_id != st.player2_peer_id:
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
            game = self._games.get(room_id)
            colors = self._colors.get(room_id)
        if st is None or game is None or colors is None:
            return
        if st.status != "playing" or game.winner_peer_id is not None:
            return
        if peer_id != game.next_peer_id:
            return
        if not game.can_place(x, y):
            return
        color = colors.get(peer_id)
        if color not in (1, 2):
            return

        game.board[y][x] = color
        game.last_move = (x, y, color)

        win_color = check_winner(game.board, x, y)
        if win_color:
            if win_color == 1:
                game.winner_peer_id = st.host_peer_id
            else:
                game.winner_peer_id = st.player2_peer_id

            st.status = "waiting"
            if st.player2_peer_id:
                st.ready[st.player2_peer_id] = False
            st.updated_ms = now_ms()
            self._announce_room(room_id)
            parts = st.participants()
            self._broadcast_room(room_id, {"type": "room_state", "room_id": room_id, "participants": parts})
            self._emit("room_state", {"room_id": room_id, "participants": parts})
        else:
            other = st.player2_peer_id if peer_id == st.host_peer_id else st.host_peer_id
            game.next_peer_id = other or st.host_peer_id
        self._broadcast_game_state(room_id)

    def _handle_game_start(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        if not room_id:
            return
        black = str(msg.get("black_peer_id", ""))
        white = str(msg.get("white_peer_id", ""))
        next_peer_id = str(msg.get("next_peer_id", black))
        game = GameState.new(next_peer_id=next_peer_id)
        with self._lock:
            self._games[room_id] = game
            self._colors[room_id] = {black: 1, white: 2}
        self._emit("game_started", {"room_id": room_id, "black_peer_id": black, "white_peer_id": white, "next_peer_id": next_peer_id})

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
            allowed = peer_id == st.host_peer_id or peer_id == st.player2_peer_id or peer_id in st.spectators
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
            game = self._games.get(room_id)
        if game is None:
            return
        flat = [cell for row in game.board for cell in row]
        self._broadcast_room(
            room_id,
            {
                "type": "game_state",
                "room_id": room_id,
                "board": flat,
                "next_peer_id": game.next_peer_id,
                "winner_peer_id": game.winner_peer_id,
                "last_move": list(game.last_move) if game.last_move else None,
            },
        )
        self._emit("game_state", {"room_id": room_id})

    def _handle_game_state(self, msg: dict[str, Any]) -> None:
        room_id = str(msg.get("room_id", ""))
        board = msg.get("board")
        if not room_id or not isinstance(board, list) or len(board) != BOARD_SIZE * BOARD_SIZE:
            return
        next_peer_id = str(msg.get("next_peer_id", ""))
        winner = str(msg.get("winner_peer_id")) if msg.get("winner_peer_id") else None
        game = GameState.new(next_peer_id=next_peer_id)
        for i, v in enumerate(board):
            y, x = divmod(i, BOARD_SIZE)
            try:
                game.board[y][x] = int(v)
            except Exception:
                game.board[y][x] = 0
        game.winner_peer_id = winner
        lm = msg.get("last_move")
        if isinstance(lm, list) and len(lm) == 3:
            try:
                game.last_move = (int(lm[0]), int(lm[1]), int(lm[2]))
            except Exception:
                pass
        with self._lock:
            self._games[room_id] = game
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
        if st.player2_peer_id:
            st.player2_nickname = self._known_nicknames.get(st.player2_peer_id, st.player2_nickname or "玩家")
        summary = st.summary()
        self._upsert_room(summary)
        self.node.broadcast({"type": "room_announce", "room": summary.__dict__})

    def _broadcast_room(self, room_id: str, msg: dict[str, Any]) -> None:
        with self._lock:
            st = self._host_rooms.get(room_id)
        if st is None:
            return
        targets = [st.host_peer_id]
        if st.player2_peer_id:
            targets.append(st.player2_peer_id)
        targets.extend(list(st.spectators))
        for pid in targets:
            if pid == self.peer_id:
                continue
            self.node.send_to_peer(pid, msg)

    def _close_host_room(self, room_id: str) -> None:
        with self._lock:
            st = self._host_rooms.pop(room_id, None)
            self.rooms.pop(room_id, None)
            self._games.pop(room_id, None)
            self._colors.pop(room_id, None)
        if st is None:
            return
        self._broadcast_room(room_id, {"type": "room_close", "room_id": room_id})
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
        with self._lock:
            for rid, r in list(self.rooms.items()):
                if r.host_peer_id == self.peer_id:
                    continue
                if r.updated_ms < cutoff and r.host_peer_id not in peers:
                    removed.append(rid)
                    del self.rooms[rid]
            for rid, st in list(self._host_rooms.items()):
                if st.status != "waiting":
                    continue
                dirty = False
                if st.player2_peer_id and st.player2_peer_id not in peers:
                    old = st.player2_peer_id
                    st.player2_peer_id = None
                    st.player2_nickname = None
                    st.ready.pop(old, None)
                    st.nicknames.pop(old, None)
                    dirty = True
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
        if removed:
            self._emit("rooms", {})
        for rid, parts in changed_host_rooms:
            self._announce_room(rid)
            self._broadcast_room(rid, {"type": "room_state", "room_id": rid, "participants": parts})
            self._emit("room_state", {"room_id": rid, "participants": parts})

    def _emit(self, etype: str, payload: dict[str, Any]) -> None:
        try:
            self._on_event(CoreEvent(type=etype, payload=payload))
        except Exception:
            pass
