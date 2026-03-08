from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...model.room import RoomSummary


class LobbyScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: "object") -> None:
        super().__init__(parent)
        self.app = app
        self._rooms: dict[str, RoomSummary] = {}
        peers_width = 480

        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(self, width=peers_width)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        card = ttk.Frame(left, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill=tk.X, padx=14, pady=(14, 10))

        ttk.Label(top, text="大厅 / 房间列表", style="SubTitle.TLabel").pack(side=tk.LEFT)

        # 房间操作按钮容器（右对齐，与大厅面板右边缘对齐）
        room_actions = ttk.Frame(top, style="Card.TFrame")
        room_actions.pack(side=tk.RIGHT)
        self._create_btn = ttk.Button(room_actions, text="创建房间", style="SmallPrimary.TButton", command=self._on_create)
        self._create_btn.pack(side=tk.LEFT)
        self._join_btn = ttk.Button(room_actions, text="加入对战", style="Small.TButton", command=self._on_join, state=tk.DISABLED)
        self._join_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._watch_btn = ttk.Button(room_actions, text="观战", style="Small.TButton", command=self._on_watch, state=tk.DISABLED)
        self._watch_btn.pack(side=tk.LEFT, padx=(6, 0))

        table = ttk.Frame(card, style="Card.TFrame")
        table.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        self.tree = ttk.Treeview(
            table,
            columns=("name", "game", "host", "addr", "status", "players", "spectators"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("name", text="房间")
        self.tree.heading("game", text="游戏")
        self.tree.heading("host", text="房主")
        self.tree.heading("addr", text="地址")
        self.tree.heading("status", text="状态")
        self.tree.heading("players", text="玩家")
        self.tree.heading("spectators", text="观战")
        self.tree.column("name", width=280, anchor=tk.CENTER)
        self.tree.column("game", width=130, anchor=tk.CENTER)
        self.tree.column("host", width=150, anchor=tk.CENTER)
        self.tree.column("addr", width=170, anchor=tk.CENTER)
        self.tree.column("status", width=120, anchor=tk.CENTER)
        self.tree.column("players", width=100, anchor=tk.CENTER)
        self.tree.column("spectators", width=100, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        peers_card = ttk.Frame(right, style="Card2.TFrame", width=peers_width)
        peers_card.pack(fill=tk.BOTH, expand=True)
        peers_card.pack_propagate(False)

        peers_top = ttk.Frame(peers_card, style="Card2.TFrame")
        peers_top.pack(fill=tk.X, padx=14, pady=(14, 10))
        ttk.Label(peers_top, text="在线用户", style="SubTitle.TLabel").pack(side=tk.LEFT)

        # 昵称操作容器（右对齐，与在线用户面板右边缘对齐）
        nick_actions = ttk.Frame(peers_top, style="Card2.TFrame")
        nick_actions.pack(side=tk.RIGHT)
        # 使用 app 的 _nick_var，确保昵称修改同步
        self._nick_var = getattr(app, "_nick_var", None) or tk.StringVar(value=getattr(app.core, "nickname", "玩家"))
        self._nick_entry = ttk.Entry(nick_actions, textvariable=self._nick_var, width=12, style="SmallNick.TEntry")
        self._nick_entry.pack(side=tk.LEFT)
        self._nick_entry.bind("<Return>", lambda _e: self._commit_nickname())
        self._nick_btn = ttk.Button(nick_actions, text="修改昵称", style="SmallPrimary.TButton", command=self._commit_nickname)
        self._nick_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.peers = tk.Listbox(
            peers_card,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 11),
            width=56,
        )
        self.peers.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def on_show(self, **_kwargs: object) -> None:
        self.set_rooms(list(getattr(self.app.core, "rooms", {}).values()))

    def set_peers(self, items: object) -> None:
        if not isinstance(items, list):
            return
        self.peers.delete(0, tk.END)
        me = str(getattr(self.app.core, "peer_id", ""))
        def peer_sort_key(item: object) -> tuple[int, str]:
            if not isinstance(item, dict):
                return (1, "")
            pid = str(item.get("peer_id", ""))
            nick = str(item.get("nickname", ""))
            return (0 if pid == me else 1, nick)
        for p in sorted(items, key=peer_sort_key):
            if not isinstance(p, dict):
                continue
            pid = str(p.get("peer_id", ""))
            nick = str(p.get("nickname", "玩家"))
            ip = str(p.get("ip", ""))
            port = int(p.get("port", 0) or 0)
            suffix = "（本机）" if pid == me else ""
            self.peers.insert(tk.END, f"{nick} {ip}:{port}{suffix}")

    def set_rooms(self, rooms: list[RoomSummary]) -> None:
        self._rooms = {r.room_id: r for r in rooms}
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in sorted(rooms, key=lambda rr: rr.updated_ms, reverse=True):
            status = self._room_status_text(r)
            game = self._game_name(getattr(r, "game", "gomoku"))
            host = r.host_nickname or r.host_peer_id[:6]
            addr = f"{r.host_ip}:{r.host_port}" if r.host_ip and r.host_port else ""
            self.tree.insert(
                "",
                tk.END,
                iid=r.room_id,
                values=(r.name, game, host, addr, status, f"{r.players}/2", str(r.spectators)),
            )
        self._refresh_action_buttons()

    def _selected_room_id(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return str(sel[0])

    def _room_status_text(self, room: RoomSummary) -> str:
        if room.status == "playing":
            return "对战中"
        if room.players >= 2:
            return "等待开始"
        return "等待加入"

    def _refresh_action_buttons(self) -> None:
        if hasattr(self.app, "_sync_game_header_actions"):
            try:
                getattr(self.app, "_sync_game_header_actions")()
            except Exception:
                pass

    def set_join_button_state(self, state: str) -> None:
        self._join_btn.configure(state=state)

    def set_watch_button_state(self, state: str) -> None:
        self._watch_btn.configure(state=state)

    def hide_actions(self) -> None:
        """非大厅界面时隐藏操作按钮（当前实现中按钮在面板内，无需额外操作）"""
        pass

    def _on_create(self) -> None:
        self._create_room()

    def _on_join(self) -> None:
        self._join_selected("play")

    def _on_watch(self) -> None:
        self._join_selected("watch")

    def _commit_nickname(self) -> None:
        if hasattr(self.app, "_commit_nickname"):
            nick = self._nick_var.get().strip()
            if nick:
                self._nick_var.set(nick)
                getattr(self.app, "_commit_nickname")()

    def _game_name(self, game: str) -> str:
        return "五子棋" if game == "gomoku" else "未知游戏"

    def _join_selected(self, want: str) -> None:
        rid = self._selected_room_id()
        if not rid:
            self.app.toast.show("请选择一个房间")
            return
        r = self._rooms.get(rid)
        if r is None:
            return
        if want == "play":
            if r.status != "waiting":
                self.app.toast.show("该房间对战中，只能观战")
                return
            if r.players >= 2:
                self.app.toast.show("房间已满，只能观战")
                return
        if want == "watch":
            if r.status != "playing":
                self.app.toast.show("仅可观战对战中的房间")
                return
        self.app.core.join_room(rid, want)

    def can_join_selected(self) -> bool:
        rid = self._selected_room_id()
        room = self._rooms.get(rid) if rid else None
        return bool(room is not None and room.status == "waiting" and room.players < 2)

    def can_watch_selected(self) -> bool:
        rid = self._selected_room_id()
        room = self._rooms.get(rid) if rid else None
        return bool(room is not None and room.status == "playing")

    def create_room_from_header(self) -> None:
        self._create_room()

    def join_selected_from_header(self) -> None:
        self._join_selected("play")

    def watch_selected_from_header(self) -> None:
        self._join_selected("watch")

    def _create_room(self) -> None:
        win = tk.Toplevel(self)
        win.title("创建房间")
        win.configure(bg="#0b1220")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        body = ttk.Frame(win, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        ttk.Label(body, text="房间名称", style="SubTitle.TLabel").pack(anchor=tk.W)
        name_var = tk.StringVar(value=f"房间-{getattr(self.app.core, 'nickname', '玩家')}")
        entry = ttk.Entry(body, textvariable=name_var, width=28, style="Nick.TEntry")
        entry.pack(fill=tk.X, pady=(8, 12))
        entry.focus_set()

        ttk.Label(body, text="游戏", style="SubTitle.TLabel").pack(anchor=tk.W)
        game_var = tk.StringVar(value="gomoku")
        ttk.Radiobutton(body, text="五子棋", variable=game_var, value="gomoku").pack(anchor=tk.W, pady=(8, 12))

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill=tk.X)

        def ok() -> None:
            rid = self.app.core.create_room(name_var.get(), game_var.get())
            win.destroy()
            self.app.show("game", room_id=rid, role="host")

        ttk.Button(btns, text="取消", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="创建", style="Primary.TButton", command=ok).pack(side=tk.RIGHT, padx=(0, 10))

    def _on_double_click(self, _e: tk.Event) -> None:
        rid = self._selected_room_id()
        if not rid:
            return
        r = self._rooms.get(rid)
        if r is None:
            return
        if r.status == "playing":
            self._join_selected("watch")
        elif r.players < 2:
            self._join_selected("play")

    def _on_tree_select(self, _e: tk.Event) -> None:
        self._refresh_action_buttons()
