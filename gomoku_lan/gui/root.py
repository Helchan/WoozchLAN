from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..core import Core, CoreEvent
from ..storage import Settings, allocate_runtime_settings, load_settings, save_settings
from ..util import now_ms
from .screens.game import GameScreen
from .screens.lobby import LobbyScreen
from .screens.room import RoomScreen
from .widgets import Toast


class RootWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Gomoku LAN")
        self.root.minsize(1120, 720)

        self._apply_theme()

        self.persistent_settings: Settings = load_settings()
        runtime_settings, self._runtime_ephemeral = allocate_runtime_settings(self.persistent_settings)
        self.core = Core(peer_id=runtime_settings.peer_id, nickname=runtime_settings.nickname, on_event=self._on_core_event)

        self._header = ttk.Frame(self.root)
        self._header.pack(fill=tk.X, padx=18, pady=(18, 12))

        self._title = ttk.Label(self._header, text="五子棋", style="Title.TLabel")
        self._title.pack(side=tk.LEFT)

        self._sub = ttk.Label(self._header, text="LAN • P2P • 即开即用", style="SubTitle.TLabel")
        self._sub.pack(side=tk.LEFT, padx=(10, 0), pady=(6, 0))

        self._right = ttk.Frame(self._header)
        self._right.pack(side=tk.RIGHT)

        self._nick_var = tk.StringVar(value=self.core.nickname)
        self._nick_entry = ttk.Entry(self._right, textvariable=self._nick_var, width=18, style="Nick.TEntry")
        self._nick_entry.pack(side=tk.LEFT)
        self._nick_entry.bind("<Return>", lambda _e: self._commit_nickname())
        self._nick_btn = ttk.Button(self._right, text="修改昵称", style="Primary.TButton", command=self._commit_nickname)
        self._nick_btn.pack(side=tk.LEFT, padx=(10, 0))

        self._status = ttk.Label(self._right, text="正在启动…", style="Hint.TLabel")
        self._status.pack(side=tk.LEFT, padx=(12, 0), pady=(6, 0))

        self._content = ttk.Frame(self.root)
        self._content.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))

        self.screens: dict[str, ttk.Frame] = {}
        self.screens["lobby"] = LobbyScreen(self._content, self)
        self.screens["room"] = RoomScreen(self._content, self)
        self.screens["game"] = GameScreen(self._content, self)

        for s in self.screens.values():
            s.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.toast = Toast(self.root)
        self._current = "lobby"
        self._room_role_by_id: dict[str, str] = {}
        self._room_chat: dict[str, list[dict[str, str]]] = {}

        self._last_rooms_refresh_ms = 0
        self.show("lobby")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def start(self) -> None:
        self.core.start()

    def show(self, name: str, **kwargs: object) -> None:
        prev = self._current
        if prev != name:
            prev_frame = self.screens.get(prev)
            if prev_frame is not None and hasattr(prev_frame, "on_hide"):
                try:
                    getattr(prev_frame, "on_hide")()
                except Exception:
                    pass
        self._current = name
        frame = self.screens[name]
        frame.lift()
        if hasattr(frame, "on_show"):
            getattr(frame, "on_show")(**kwargs)

    def _commit_nickname(self) -> None:
        nick = self._nick_var.get().strip()
        if not nick:
            return
        self.core.set_nickname(nick)
        self.persistent_settings = Settings(peer_id=self.persistent_settings.peer_id, nickname=nick)
        save_settings(self.persistent_settings)
        self.toast.show("昵称已更新")

    def _on_core_event(self, ev: CoreEvent) -> None:
        self.root.after(0, lambda: self._on_core_event_ui(ev))

    def _on_core_event_ui(self, ev: CoreEvent) -> None:
        if ev.type == "node":
            ip = str(ev.payload.get("ip", ""))
            port = int(ev.payload.get("port", 0) or 0)
            self._status.configure(text=f"本机：{ip}:{port}")
            return
        if ev.type == "peers":
            lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
            lobby.set_peers(ev.payload.get("items", []))
            return
        if ev.type == "rooms":
            now = now_ms()
            if now - self._last_rooms_refresh_ms < 120:
                return
            self._last_rooms_refresh_ms = now
            lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
            lobby.set_rooms(list(self.core.rooms.values()))
            if self._current == "room":
                room: RoomScreen = self.screens["room"]  # type: ignore[assignment]
                room.refresh_header()
            return
        if ev.type == "room_entered":
            rid = str(ev.payload.get("room_id", ""))
            role = str(ev.payload.get("role", "spectator"))
            if rid:
                self._room_role_by_id[rid] = role
                self._room_chat.setdefault(rid, [])
            if rid:
                status = str(ev.payload.get("status", ""))
                room = self.core.rooms.get(rid)
                if not status and room is not None:
                    status = room.status
                if status == "playing" and role == "spectator":
                    self.show("game", room_id=rid)
                else:
                    self.show("room", **ev.payload)
            else:
                self.show("room", **ev.payload)
            return
        if ev.type == "room_left":
            rid = str(ev.payload.get("room_id", ""))
            if rid:
                self._room_role_by_id.pop(rid, None)
                self._room_chat.pop(rid, None)
            self.show("lobby")
            return
        if ev.type == "room_state":
            room: RoomScreen = self.screens["room"]  # type: ignore[assignment]
            if self._current == "room":
                room.update_participants(ev.payload.get("participants"))
            return
        if ev.type == "toast":
            self.toast.show(str(ev.payload.get("text", "")) or "提示")
            return
        if ev.type == "game_started":
            self.show("game", **ev.payload)
            return
        if ev.type == "game_state":
            game: GameScreen = self.screens["game"]  # type: ignore[assignment]
            if self._current == "game":
                game.refresh()
            return

        if ev.type == "chat":
            rid = str(ev.payload.get("room_id", ""))
            if rid:
                self._room_chat.setdefault(rid, []).append(
                    {
                        "nickname": str(ev.payload.get("nickname", "玩家")),
                        "text": str(ev.payload.get("text", "")),
                    }
                )
                self._room_chat[rid] = self._room_chat[rid][-200:]
                if self._current == "room":
                    room: RoomScreen = self.screens["room"]  # type: ignore[assignment]
                    room.refresh_chat()
                if self._current == "game":
                    game: GameScreen = self.screens["game"]  # type: ignore[assignment]
                    game.refresh_chat()
            return

    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#0b1220"
        panel = "#0f1b33"
        panel2 = "#0d172d"
        border = "#1f2a44"
        fg = "#e5e7eb"
        subtle = "#94a3b8"
        accent = "#22c55e"
        warn = "#f59e0b"

        self.root.configure(bg=bg)

        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=panel)
        style.configure("Card2.TFrame", background=panel2)
        style.configure("TLabel", background=bg, foreground=fg, font=("Helvetica", 12))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Helvetica", 26, "bold"))
        style.configure("SubTitle.TLabel", background=bg, foreground=subtle, font=("Helvetica", 12, "bold"))
        style.configure("Hint.TLabel", background=bg, foreground=subtle, font=("Helvetica", 12))
        style.configure("Danger.TLabel", background=bg, foreground=warn, font=("Helvetica", 12, "bold"))

        style.configure(
            "TButton",
            padding=(12, 9),
            font=("Helvetica", 12, "bold"),
            background=border,
            foreground=fg,
        )
        style.map(
            "TButton",
            background=[("active", "#243252")],
        )
        style.configure(
            "Primary.TButton",
            background=accent,
            foreground="#052e16",
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#16a34a"), ("disabled", "#14532d")],
        )
        style.configure(
            "Nick.TEntry",
            padding=(10, 8),
            fieldbackground=panel,
            foreground=fg,
            insertcolor=fg,
        )
        style.configure(
            "Treeview",
            background=panel,
            fieldbackground=panel,
            foreground=fg,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            rowheight=30,
            font=("Helvetica", 12),
        )
        style.configure(
            "Treeview.Heading",
            background=panel2,
            foreground=subtle,
            font=("Helvetica", 11, "bold"),
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#1a2c4c")])

    def _on_close(self) -> None:
        try:
            self.core.stop()
        finally:
            self.root.destroy()
