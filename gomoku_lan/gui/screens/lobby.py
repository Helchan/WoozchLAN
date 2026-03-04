from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...model.room import RoomSummary


class LobbyScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: "object") -> None:
        super().__init__(parent)
        self.app = app
        self._rooms: dict[str, RoomSummary] = {}

        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(self)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        card = ttk.Frame(left, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill=tk.X, padx=14, pady=(14, 10))

        ttk.Label(top, text="大厅 / 房间列表", style="SubTitle.TLabel").pack(side=tk.LEFT)

        btns = ttk.Frame(top, style="Card.TFrame")
        btns.pack(side=tk.RIGHT)
        ttk.Button(btns, text="创建房间", style="Primary.TButton", command=self._create_room).pack(side=tk.LEFT)
        ttk.Button(btns, text="加入对战", command=lambda: self._join_selected("play")).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btns, text="观战", command=lambda: self._join_selected("watch")).pack(side=tk.LEFT, padx=(10, 0))

        table = ttk.Frame(card, style="Card.TFrame")
        table.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        self.tree = ttk.Treeview(
            table,
            columns=("name", "host", "addr", "status", "players", "spectators"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("name", text="房间")
        self.tree.heading("host", text="房主")
        self.tree.heading("addr", text="地址")
        self.tree.heading("status", text="状态")
        self.tree.heading("players", text="玩家")
        self.tree.heading("spectators", text="观战")
        self.tree.column("name", width=340, anchor=tk.W)
        self.tree.column("host", width=160, anchor=tk.W)
        self.tree.column("addr", width=170, anchor=tk.W)
        self.tree.column("status", width=120, anchor=tk.CENTER)
        self.tree.column("players", width=100, anchor=tk.CENTER)
        self.tree.column("spectators", width=100, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)

        peers_card = ttk.Frame(right, style="Card2.TFrame")
        peers_card.pack(fill=tk.BOTH, expand=True)
        ttk.Label(peers_card, text="已发现的同伴", style="SubTitle.TLabel").pack(anchor=tk.W, padx=14, pady=(14, 10))
        self.peers = tk.Listbox(
            peers_card,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 11),
        )
        self.peers.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def on_show(self, **_kwargs: object) -> None:
        self.set_rooms(list(getattr(self.app.core, "rooms", {}).values()))

    def set_peers(self, items: object) -> None:
        if not isinstance(items, list):
            return
        self.peers.delete(0, tk.END)
        for p in sorted(items, key=lambda x: str(x.get("nickname", "")) if isinstance(x, dict) else ""):
            if not isinstance(p, dict):
                continue
            nick = str(p.get("nickname", "玩家"))
            ip = str(p.get("ip", ""))
            port = int(p.get("port", 0) or 0)
            self.peers.insert(tk.END, f"{nick}  {ip}:{port}")

    def set_rooms(self, rooms: list[RoomSummary]) -> None:
        self._rooms = {r.room_id: r for r in rooms}
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in sorted(rooms, key=lambda rr: rr.updated_ms, reverse=True):
            status = "等待加入" if r.status == "waiting" else "对战中"
            host = r.host_nickname or r.host_peer_id[:6]
            addr = f"{r.host_ip}:{r.host_port}" if r.host_ip and r.host_port else ""
            self.tree.insert(
                "",
                tk.END,
                iid=r.room_id,
                values=(r.name, host, addr, status, f"{r.players}/2", str(r.spectators)),
            )

    def _selected_room_id(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return str(sel[0])

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
            if r.status == "waiting" and r.players < 2:
                self.app.toast.show("二缺一时只能加入对战")
                return
        self.app.core.join_room(rid, want)

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

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill=tk.X)

        def ok() -> None:
            rid = self.app.core.create_room(name_var.get())
            win.destroy()
            self.app.show("room", room_id=rid, role="host")

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
        else:
            self._join_selected("play")
