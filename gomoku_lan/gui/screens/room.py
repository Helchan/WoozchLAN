from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...model.room import RoomSummary


class RoomScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: "object") -> None:
        super().__init__(parent)
        self.app = app

        self.room_id: str | None = None
        self.role: str = "spectator"
        self._participants: dict[str, object] = {}
        self._ready_state = False

        card = ttk.Frame(self, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(card, style="Card.TFrame")
        header.pack(fill=tk.X, padx=14, pady=(14, 10))

        self.title = ttk.Label(header, text="房间", style="SubTitle.TLabel")
        self.title.pack(side=tk.LEFT)

        self.meta = ttk.Label(header, text="", style="Hint.TLabel")
        self.meta.pack(side=tk.LEFT, padx=(12, 0), pady=(2, 0))

        self.btn_leave = ttk.Button(header, text="退出房间", command=self._leave)
        self.btn_leave.pack(side=tk.RIGHT)

        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        left = ttk.Frame(body, style="Card.TFrame")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body, style="Card2.TFrame")
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

        top_left = ttk.Frame(left, style="Card.TFrame")
        top_left.pack(fill=tk.BOTH, expand=True)

        bottom_left = ttk.Frame(left, style="Card2.TFrame")
        bottom_left.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        ttk.Label(top_left, text="参与者", style="SubTitle.TLabel").pack(anchor=tk.W, pady=(0, 10))
        self.participants = tk.Listbox(
            top_left,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 12),
        )
        self.participants.pack(fill=tk.BOTH, expand=True)

        ttk.Label(bottom_left, text="房间聊天", style="SubTitle.TLabel").pack(anchor=tk.W, padx=12, pady=(12, 10))
        self.chat = tk.Listbox(
            bottom_left,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 11),
        )
        self.chat.pack(fill=tk.BOTH, expand=True, padx=12)

        chat_bar = ttk.Frame(bottom_left, style="Card2.TFrame")
        chat_bar.pack(fill=tk.X, padx=12, pady=12)
        self._chat_var = tk.StringVar(value="")
        self._chat_entry = ttk.Entry(chat_bar, textvariable=self._chat_var, style="Nick.TEntry")
        self._chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._chat_entry.bind("<Return>", lambda _e: self._send_chat())
        ttk.Button(chat_bar, text="发送", style="Primary.TButton", command=self._send_chat).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(right, text="操作", style="SubTitle.TLabel").pack(anchor=tk.W, padx=14, pady=(14, 10))
        self.ready_btn = ttk.Button(right, text="准备", style="Primary.TButton", command=self._toggle_ready)
        self.ready_btn.pack(fill=tk.X, padx=14, pady=(0, 10))

        self.start_btn = ttk.Button(right, text="开始对战", style="Primary.TButton", command=self._start)
        self.start_btn.pack(fill=tk.X, padx=14, pady=(0, 10))

        self.reset_btn = ttk.Button(right, text="再来一局", command=self._reset)
        self.reset_btn.pack(fill=tk.X, padx=14, pady=(0, 10))

        self.go_game_btn = ttk.Button(right, text="进入棋盘", command=self._go_game)
        self.go_game_btn.pack(fill=tk.X, padx=14, pady=(0, 10))

        self.note = ttk.Label(right, text="等待双方准备后由房主开始", style="Hint.TLabel", wraplength=220)
        self.note.pack(anchor=tk.W, padx=14, pady=(6, 14))

    def on_show(self, room_id: str, role: str = "spectator", participants: object = None, **_kwargs: object) -> None:
        self.room_id = room_id
        self.role = role
        self._ready_state = False
        self.update_participants(participants)
        self.refresh_header()
        self.refresh_chat()
        self._refresh_controls()

    def refresh_chat(self) -> None:
        if not self.room_id:
            return
        buf = getattr(self.app, "_room_chat", {}).get(self.room_id, [])
        self.chat.delete(0, tk.END)
        for item in buf[-120:]:
            nick = str(item.get("nickname", "玩家"))
            text = str(item.get("text", ""))
            self.chat.insert(tk.END, f"{nick}：{text}")
        if self.chat.size() > 0:
            self.chat.see(tk.END)

    def refresh_header(self) -> None:
        if not self.room_id:
            return
        r: RoomSummary | None = getattr(self.app.core, "rooms", {}).get(self.room_id)
        if r is not None:
            status = self._room_status_text(r)
            self.title.configure(text=f"房间：{r.name}")
            host = r.host_nickname or r.host_peer_id[:6]
            addr = f"{r.host_ip}:{r.host_port}" if r.host_ip and r.host_port else ""
            self.meta.configure(text=f"{status} • 房主 {host} • {addr} • 玩家 {r.players}/2 • 观战 {r.spectators}")
        else:
            self.title.configure(text=f"房间：{self.room_id}")
            self.meta.configure(text=f"角色：{self.role}")

    def _room_status_text(self, room: RoomSummary) -> str:
        if room.status == "playing":
            return "对战中"
        if room.players >= 2:
            return "等待开始"
        return "等待加入"

    def update_participants(self, participants: object) -> None:
        if isinstance(participants, dict):
            self._participants = participants
        self.participants.delete(0, tk.END)
        host = str(self._participants.get("host_peer_id", ""))
        p2 = str(self._participants.get("player2_peer_id", "")) if self._participants.get("player2_peer_id") else ""
        spectators = self._participants.get("spectators")
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        nicknames = self._participants.get("nicknames") if isinstance(self._participants.get("nicknames"), dict) else {}

        def add_line(label: str, pid: str) -> None:
            if not pid:
                return
            if pid == host:
                flag = "[房主]"
            else:
                flag = "[已准备]" if isinstance(ready, dict) and ready.get(pid) else "[未准备]"
            nick = str(nicknames.get(pid, "")) if isinstance(nicknames, dict) else ""
            show = nick if nick else pid[:6]
            self.participants.insert(tk.END, f"{label}  {show}  {flag}")

        add_line("房主", host)
        add_line("对手", p2)
        if isinstance(spectators, list) and spectators:
            self.participants.insert(tk.END, "")
            self.participants.insert(tk.END, "观战：")
            for sid in spectators:
                s = str(sid)
                nick = str(nicknames.get(s, "")) if isinstance(nicknames, dict) else ""
                self.participants.insert(tk.END, f"  · {nick if nick else s[:6]}")
        self.refresh_header()
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        is_host = self.role == "host"
        is_player2 = self.role == "player2"
        is_player = is_host or is_player2
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        p2 = str(self._participants.get("player2_peer_id", "")) if self._participants.get("player2_peer_id") else ""
        can_start = bool(is_host and p2 and isinstance(ready, dict) and ready.get(p2))
        my_id = getattr(self.app.core, "peer_id", "")
        if self.role == "player2" and isinstance(ready, dict):
            self._ready_state = bool(ready.get(my_id))
        self.ready_btn.configure(text=("取消" if self._ready_state else "准备"))
        game = getattr(self.app.core, "_games", {}).get(self.room_id) if self.room_id else None
        can_reset = bool(is_host and game is not None and getattr(game, "winner_peer_id", None))

        if is_host:
            if self.ready_btn.winfo_manager():
                self.ready_btn.pack_forget()
        else:
            if not self.ready_btn.winfo_manager():
                self.ready_btn.pack(fill=tk.X, padx=14, pady=(0, 10))
            self.ready_btn.configure(state=(tk.NORMAL if is_player else tk.DISABLED))

        self.start_btn.configure(state=(tk.NORMAL if can_start else tk.DISABLED))
        self.reset_btn.configure(state=(tk.NORMAL if can_reset else tk.DISABLED))
        self.go_game_btn.configure(state=tk.NORMAL)
        if self.role == "spectator":
            self.note.configure(text="你正在观战。若想对战，请在大厅加入等待中的房间。")
        elif self.role == "player2":
            self.note.configure(text="点击准备后等待房主开始对战。")
        else:
            self.note.configure(text="对手准备后即可开始对战。")

    def _toggle_ready(self) -> None:
        if not self.room_id:
            return
        self._ready_state = not self._ready_state
        self.ready_btn.configure(text=("取消" if self._ready_state else "准备"))
        self.app.core.set_ready(self.room_id, self._ready_state)

    def _start(self) -> None:
        if not self.room_id:
            return
        self.app.core.start_game(self.room_id)

    def _leave(self) -> None:
        if not self.room_id:
            return
        self.app.core.leave_room(self.room_id)

    def _send_chat(self) -> None:
        if not self.room_id:
            return
        text = self._chat_var.get()
        if not text.strip():
            return
        self._chat_var.set("")
        self.app.core.send_chat(self.room_id, text)

    def _reset(self) -> None:
        if not self.room_id:
            return
        self.app.core.reset_game(self.room_id)

    def _go_game(self) -> None:
        if not self.room_id:
            return
        self.app.show("game", room_id=self.room_id)
