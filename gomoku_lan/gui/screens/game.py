from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import time

from ...model.game import BOARD_SIZE


class GameScreen(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: "object") -> None:
        super().__init__(parent)
        self.app = app
        self.room_id: str | None = None
        self.black_peer_id: str | None = None
        self.white_peer_id: str | None = None
        self._winner_modal_for: str | None = None
        self._turn_peer_id: str | None = None
        self._turn_started_s = time.monotonic()
        self._timer_job: str | None = None

        card = ttk.Frame(self, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(card, style="Card.TFrame")
        header.pack(fill=tk.X, padx=14, pady=(14, 10))

        self.title = ttk.Label(header, text="棋盘", style="SubTitle.TLabel")
        self.title.pack(side=tk.LEFT)

        self.status = ttk.Label(header, text="", style="Hint.TLabel")
        self.status.pack(side=tk.LEFT, padx=(12, 0), pady=(2, 0))

        self.timer = ttk.Label(header, text="", style="Hint.TLabel")
        self.timer.pack(side=tk.LEFT, padx=(12, 0), pady=(2, 0))

        ttk.Button(header, text="返回房间", command=self._back).pack(side=tk.RIGHT)

        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        left = ttk.Frame(body, style="Card.TFrame")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body, style="Card2.TFrame", width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        self.canvas = tk.Canvas(left, bg="#e7cfa5", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

        ttk.Label(right, text="聊天", style="SubTitle.TLabel").pack(anchor=tk.W, padx=12, pady=(12, 10))
        self.chat = tk.Listbox(
            right,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 11),
        )
        self.chat.pack(fill=tk.BOTH, expand=True, padx=12)

        bar = ttk.Frame(right, style="Card2.TFrame")
        bar.pack(fill=tk.X, padx=12, pady=12)
        self._chat_var = tk.StringVar(value="")
        self._chat_entry = ttk.Entry(bar, textvariable=self._chat_var, style="Nick.TEntry")
        self._chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._chat_entry.bind("<Return>", lambda _e: self._send_chat())
        ttk.Button(bar, text="发送", style="Primary.TButton", command=self._send_chat).pack(side=tk.LEFT, padx=(10, 0))

        self._cell = 36
        self._origin = (20, 20)

    def on_show(self, room_id: str, black_peer_id: str | None = None, white_peer_id: str | None = None, **_kwargs: object) -> None:
        self.room_id = room_id
        self._winner_modal_for = None
        self._turn_peer_id = None
        self._turn_started_s = time.monotonic()
        if black_peer_id:
            self.black_peer_id = black_peer_id
        if white_peer_id:
            self.white_peer_id = white_peer_id
        self.title.configure(text=f"棋盘 • 房间 {room_id[:8]}")
        self.refresh_chat()
        self.refresh()
        self._ensure_timer()

    def on_hide(self) -> None:
        if self._timer_job:
            try:
                self.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None

    def refresh_chat(self) -> None:
        if not self.room_id:
            return
        buf = getattr(self.app, "_room_chat", {}).get(self.room_id, [])
        self.chat.delete(0, tk.END)
        for item in buf[-160:]:
            nick = str(item.get("nickname", "玩家"))
            text = str(item.get("text", ""))
            self.chat.insert(tk.END, f"{nick}：{text}")
        if self.chat.size() > 0:
            self.chat.see(tk.END)

    def refresh(self) -> None:
        if not self.room_id:
            return
        room = getattr(self.app.core, "rooms", {}).get(self.room_id)
        if room is not None:
            name = getattr(room, "name", "") or self.room_id[:8]
            host = getattr(room, "host_nickname", "") or getattr(room, "host_peer_id", "")[:6]
            spectators = getattr(room, "spectators", 0)
            self.title.configure(text=f"棋盘 • {name} • 房主 {host} • 观战 {spectators}")
        game = getattr(self.app.core, "_games", {}).get(self.room_id)
        if game is None:
            self.status.configure(text="等待房主开始…")
            self.timer.configure(text="")
            self._redraw()
            return
        my_id = getattr(self.app.core, "peer_id", "")
        nicks = getattr(self.app.core, "_known_nicknames", {})
        colors = getattr(self.app.core, "_colors", {}).get(self.room_id, {})

        def name(pid: str) -> str:
            if isinstance(nicks, dict) and pid in nicks:
                return str(nicks.get(pid) or pid[:6])
            return pid[:6]

        my_color = colors.get(my_id)
        if my_color == 1:
            role = "你是黑"
        elif my_color == 2:
            role = "你是白"
        else:
            role = "观战"

        opponent = ""
        if my_color in (1, 2):
            for pid, c in colors.items():
                if pid != my_id and c in (1, 2):
                    opponent = name(pid)
                    break

        is_my_turn = game.next_peer_id == my_id
        turn = "轮到你下子" if is_my_turn else f"轮到 {name(game.next_peer_id)} 下子"
        if game.winner_peer_id:
            if game.winner_peer_id == my_id:
                turn = "你赢了"
            else:
                turn = f"胜者：{name(game.winner_peer_id)}"
        tail = f" • 对手 {opponent}" if opponent else ""
        self.status.configure(text=f"{role}{tail} • {turn}")

        if game.winner_peer_id is None and self._turn_peer_id != game.next_peer_id:
            self._turn_peer_id = game.next_peer_id
            self._turn_started_s = time.monotonic()
        if game.winner_peer_id is not None:
            self._turn_peer_id = None
            self.timer.configure(text="")
        self._redraw()

        if game.winner_peer_id:
            token = f"{self.room_id}:{game.winner_peer_id}"
            if self._winner_modal_for != token:
                self._winner_modal_for = token
                self._show_winner_modal(game.winner_peer_id)

    def _ensure_timer(self) -> None:
        if self._timer_job is not None:
            return
        self._tick_timer()

    def _tick_timer(self) -> None:
        if not self.room_id:
            self._timer_job = None
            return
        game = getattr(self.app.core, "_games", {}).get(self.room_id)
        if game is None or game.winner_peer_id is not None or self._turn_peer_id is None:
            self.timer.configure(text="")
        else:
            elapsed = max(0.0, time.monotonic() - self._turn_started_s)
            sec = int(elapsed)
            mm, ss = divmod(sec, 60)
            self.timer.configure(text=f"计时 {mm:02d}:{ss:02d}")
        self._timer_job = self.after(200, self._tick_timer)

    def _back(self) -> None:
        if self.room_id:
            role = getattr(self.app, "_room_role_by_id", {}).get(self.room_id, "spectator")
            self.app.show("room", room_id=self.room_id, role=role)
        else:
            self.app.show("lobby")

    def _metrics(self) -> tuple[int, int, int]:
        w = max(200, int(self.canvas.winfo_width()))
        h = max(200, int(self.canvas.winfo_height()))
        size = min(w, h) - 40
        cell = max(18, size // (BOARD_SIZE - 1))
        ox = (w - cell * (BOARD_SIZE - 1)) // 2
        oy = (h - cell * (BOARD_SIZE - 1)) // 2
        return ox, oy, cell

    def _redraw(self) -> None:
        self.canvas.delete("all")
        ox, oy, cell = self._metrics()
        self._origin = (ox, oy)
        self._cell = cell

        for i in range(BOARD_SIZE):
            x = ox + i * cell
            y0 = oy
            y1 = oy + (BOARD_SIZE - 1) * cell
            self.canvas.create_line(x, y0, x, y1, fill="#6b4f2a")
        for i in range(BOARD_SIZE):
            y = oy + i * cell
            x0 = ox
            x1 = ox + (BOARD_SIZE - 1) * cell
            self.canvas.create_line(x0, y, x1, y, fill="#6b4f2a")

        stars = [(3, 3), (11, 3), (7, 7), (3, 11), (11, 11)]
        for sx, sy in stars:
            cx = ox + sx * cell
            cy = oy + sy * cell
            self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#6b4f2a", outline="")

        if not self.room_id:
            return
        game = getattr(self.app.core, "_games", {}).get(self.room_id)
        if game is None:
            return
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                v = game.board[y][x]
                if v == 0:
                    continue
                cx = ox + x * cell
                cy = oy + y * cell
                r = max(7, cell // 2 - 2)
                if v == 1:
                    self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#111827", outline="#f8fafc", width=2)
                else:
                    self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#f8fafc", outline="#334155", width=2)
        if game.last_move:
            x, y, _c = game.last_move
            cx = ox + x * cell
            cy = oy + y * cell
            r = max(9, cell // 2 - 1)
            self.canvas.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline="#22c55e", width=2)

    def _on_click(self, e: tk.Event) -> None:
        if not self.room_id:
            return
        game = getattr(self.app.core, "_games", {}).get(self.room_id)
        if game is None:
            return
        if game.winner_peer_id:
            return

        my_id = getattr(self.app.core, "peer_id", "")
        if game.next_peer_id != my_id:
            return

        ox, oy = self._origin
        cell = self._cell
        x = int(round((e.x - ox) / cell))
        y = int(round((e.y - oy) / cell))
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return
        self.app.core.play_move(self.room_id, x, y)

    def _send_chat(self) -> None:
        if not self.room_id:
            return
        text = self._chat_var.get()
        if not text.strip():
            return
        self._chat_var.set("")
        self.app.core.send_chat(self.room_id, text)

    def _show_winner_modal(self, winner_peer_id: str) -> None:
        if not self.room_id:
            return
        my_id = getattr(self.app.core, "peer_id", "")
        nicks = getattr(self.app.core, "_known_nicknames", {})

        def name(pid: str) -> str:
            if isinstance(nicks, dict) and pid in nicks:
                return str(nicks.get(pid) or pid[:6])
            return pid[:6]

        win = tk.Toplevel(self)
        win.title("对局结束")
        win.configure(bg="#0b1220")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        body = ttk.Frame(win, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        title = "你赢了" if winner_peer_id == my_id else f"胜者：{name(winner_peer_id)}"
        ttk.Label(body, text=title, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(body, text="你可以返回房间，或由房主重置棋盘再来一局。", style="Hint.TLabel").pack(anchor=tk.W, pady=(8, 14))

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill=tk.X)

        def back() -> None:
            win.destroy()
            self._back()

        ttk.Button(btns, text="返回房间", command=back).pack(side=tk.RIGHT)

        role = getattr(self.app, "_room_role_by_id", {}).get(self.room_id, "spectator")
        if role == "host":
            def again() -> None:
                win.destroy()
                self.app.core.reset_game(self.room_id)
                self._back()

            ttk.Button(btns, text="再来一局", style="Primary.TButton", command=again).pack(side=tk.RIGHT, padx=(0, 10))
