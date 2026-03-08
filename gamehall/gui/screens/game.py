from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import time

from ...game.renderer import RendererRegistry, GameRenderer
from ...model.game import GameStateWrapper


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
        self.role: str = "spectator"
        self._participants: dict[str, object] = {}
        self._ready_state = False
        self._renderer: GameRenderer | None = None
        self._game_container: tk.Frame | None = None

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

        body = ttk.Frame(card, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        self._left = ttk.Frame(body, style="Card.TFrame")
        self._left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body, style="Card2.TFrame", width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        ttk.Label(right, text="成员", style="SubTitle.TLabel").pack(anchor=tk.W, padx=12, pady=(12, 10))
        self.participants = tk.Listbox(
            right,
            bg="#0f1b33",
            fg="#e5e7eb",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Helvetica", 11),
            height=9,
        )
        self.participants.pack(fill=tk.X, padx=12)

        ttk.Label(right, text="操作", style="SubTitle.TLabel").pack(anchor=tk.W, padx=12, pady=(12, 8))

        self.note = ttk.Label(right, text="等待双方准备后由房主开始", style="Hint.TLabel", wraplength=280)
        self.note.pack(anchor=tk.W, padx=12, pady=(0, 12))

        ttk.Label(right, text="聊天", style="SubTitle.TLabel").pack(anchor=tk.W, padx=12, pady=(2, 10))
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

    def on_show(
        self,
        room_id: str,
        black_peer_id: str | None = None,
        white_peer_id: str | None = None,
        role: str = "spectator",
        participants: object = None,
        **_kwargs: object,
    ) -> None:
        self.room_id = room_id
        self.role = role
        self._winner_modal_for = None
        self._turn_peer_id = None
        self._turn_started_s = time.monotonic()
        self._ready_state = False
        if black_peer_id:
            self.black_peer_id = black_peer_id
        if white_peer_id:
            self.white_peer_id = white_peer_id
        self.title.configure(text=f"棋盘 • 房间 {room_id[:8]}")
        
        # 获取房间的游戏类型并动态创建渲染器
        room = getattr(self.app.core, "rooms", {}).get(room_id)
        game_name = getattr(room, "game", "gobang") if room else "gobang"
        self._setup_renderer(game_name)
        
        self.update_participants(participants)
        self.refresh_chat()
        self.refresh()
        self._ensure_timer()

    def _setup_renderer(self, game_name: str) -> None:
        """动态创建游戏渲染器"""
        # 清理旧渲染器
        if self._renderer:
            self._renderer.destroy()
            self._renderer = None
        if self._game_container:
            self._game_container.destroy()
            self._game_container = None
        
        # 创建新渲染器
        renderer_class = RendererRegistry.get_renderer(game_name)
        if renderer_class is None:
            return
        
        self._game_container = tk.Frame(self._left)
        self._game_container.pack(fill=tk.BOTH, expand=True)
        
        self._renderer = renderer_class(
            parent=self._game_container,
            core=self.app.core,
            room_id=self.room_id or "",
        )
        widget = self._renderer.create_widget()
        widget.pack(fill=tk.BOTH, expand=True)

    def on_hide(self) -> None:
        if self._timer_job:
            try:
                self.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None
        # 清理渲染器
        if self._renderer:
            self._renderer.destroy()
            self._renderer = None

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
        
        wrapper = getattr(self.app.core, "_games", {}).get(self.room_id)
        if wrapper is None or not isinstance(wrapper, GameStateWrapper):
            self.status.configure(text="等待房主开始…")
            self.timer.configure(text="")
            if self._renderer:
                self._renderer.render(None)
            self._refresh_controls()
            return
        
        game_state = wrapper.state
        my_id = getattr(self.app.core, "peer_id", "")
        nicks = getattr(self.app.core, "_known_nicknames", {})
        
        # 委托给渲染器生成状态文本
        if self._renderer:
            status_text = self._renderer.get_status_text(game_state, my_id, nicks)
            self.status.configure(text=status_text)
            self._renderer.render(game_state)
        
        # 更新计时器（通用逻辑：检查游戏状态是否有 next_peer_id 和 winner_peer_id）
        next_peer_id = getattr(game_state, "next_peer_id", None)
        winner_peer_id = getattr(game_state, "winner_peer_id", None)
        
        if winner_peer_id is None and next_peer_id and self._turn_peer_id != next_peer_id:
            self._turn_peer_id = next_peer_id
            self._turn_started_s = time.monotonic()
        if winner_peer_id is not None:
            self._turn_peer_id = None
            self.timer.configure(text="")

        if winner_peer_id:
            token = f"{self.room_id}:{winner_peer_id}"
            if self._winner_modal_for != token:
                self._winner_modal_for = token
                self._show_winner_modal(winner_peer_id, game_state)
        self._refresh_controls()

    def update_participants(self, participants: object) -> None:
        if isinstance(participants, dict):
            self._participants = participants
        self.participants.delete(0, tk.END)
        host = str(self._participants.get("host_peer_id", ""))
        p2 = str(self._participants.get("player2_peer_id", "")) if self._participants.get("player2_peer_id") else ""
        spectators = self._participants.get("spectators")
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        nicknames = self._participants.get("nicknames") if isinstance(self._participants.get("nicknames"), dict) else {}

        def add_line(label: str, pid: str, host_player: bool = False) -> None:
            nick = str(nicknames.get(pid, "")) if isinstance(nicknames, dict) else ""
            show = nick if nick else pid[:6]
            if host_player:
                flag = "（房主）"
            else:
                flag = "（已准备）" if isinstance(ready, dict) and ready.get(pid) else "（准备中）"
            self.participants.insert(tk.END, f"{label}：{show}{flag}")

        if host:
            add_line("玩家一", host, host_player=True)
        else:
            self.participants.insert(tk.END, "玩家一：待加入")
        if p2:
            add_line("玩家二", p2)
        else:
            self.participants.insert(tk.END, "玩家二：待加入")

        if isinstance(spectators, list):
            if spectators:
                self.participants.insert(tk.END, "观战成员：")
                for sid in spectators:
                    s = str(sid)
                    nick = str(nicknames.get(s, "")) if isinstance(nicknames, dict) else ""
                    self.participants.insert(tk.END, f"  · {nick if nick else s[:6]}")
            else:
                self.participants.insert(tk.END, "观战成员：暂无")
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        my_id = getattr(self.app.core, "peer_id", "")
        if self.role == "player2" and isinstance(ready, dict):
            self._ready_state = bool(ready.get(my_id))
        if self.role == "spectator":
            self.note.configure(text="你正在观战。")
        elif self.role == "player2":
            self.note.configure(text="你是玩家二，点击准备后等待房主开始对战。")
        else:
            self.note.configure(text="仅当玩家二已准备，才可开始对战。")
        if hasattr(self.app, "_sync_game_header_actions"):
            try:
                getattr(self.app, "_sync_game_header_actions")()
            except Exception:
                pass

    def _ensure_timer(self) -> None:
        if self._timer_job is not None:
            return
        self._tick_timer()

    def _tick_timer(self) -> None:
        if not self.room_id:
            self._timer_job = None
            return
        wrapper = getattr(self.app.core, "_games", {}).get(self.room_id)
        game_state = wrapper.state if isinstance(wrapper, GameStateWrapper) else None
        winner_peer_id = getattr(game_state, "winner_peer_id", None) if game_state else None
        if game_state is None or winner_peer_id is not None or self._turn_peer_id is None:
            self.timer.configure(text="")
        else:
            elapsed = max(0.0, time.monotonic() - self._turn_started_s)
            sec = int(elapsed)
            mm, ss = divmod(sec, 60)
            self.timer.configure(text=f"计时 {mm:02d}:{ss:02d}")
        self._timer_job = self.after(200, self._tick_timer)

    def _back(self) -> None:
        if self.room_id:
            self.app.core.leave_room(self.room_id)
            return
        self.app.show("lobby")

    def can_start_game(self) -> bool:
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        p2 = str(self._participants.get("player2_peer_id", "")) if self._participants.get("player2_peer_id") else ""
        return bool(self.role == "host" and p2 and isinstance(ready, dict) and ready.get(p2))

    def can_toggle_ready(self) -> bool:
        return bool(self.role == "player2" and self.room_id)

    def ready_button_text(self) -> str:
        return "取消准备" if self._ready_state else "准备"

    def _send_chat(self) -> None:
        if not self.room_id:
            return
        text = self._chat_var.get()
        if not text.strip():
            return
        self._chat_var.set("")
        self.app.core.send_chat(self.room_id, text)

    def _toggle_ready(self) -> None:
        if not self.room_id:
            return
        self._ready_state = not self._ready_state
        self.app.core.set_ready(self.room_id, self._ready_state)
        if hasattr(self.app, "_sync_game_header_actions"):
            try:
                getattr(self.app, "_sync_game_header_actions")()
            except Exception:
                pass

    def _start(self) -> None:
        if not self.room_id:
            return
        ready = self._participants.get("ready") if isinstance(self._participants.get("ready"), dict) else {}
        p2 = str(self._participants.get("player2_peer_id", "")) if self._participants.get("player2_peer_id") else ""
        can_start = bool(self.role == "host" and p2 and isinstance(ready, dict) and ready.get(p2))
        if not can_start:
            self.app.toast.show("玩家二准备后才可开始对战")
            return
        self.app.core.start_game(self.room_id)

    def _leave(self) -> None:
        if not self.room_id:
            return
        self.app.core.leave_room(self.room_id)

    def _show_winner_modal(self, winner_peer_id: str, game_state: object) -> None:
        if not self.room_id:
            return
        my_id = getattr(self.app.core, "peer_id", "")
        nicks = getattr(self.app.core, "_known_nicknames", {})
        # 从游戏状态获取 colors（适用于五子棋等回合制游戏）
        colors = getattr(game_state, "colors", {}) or {}

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

        my_color = colors.get(my_id) if isinstance(colors, dict) else None
        if winner_peer_id == my_id:
            title = "你赢了"
        elif my_color in (1, 2):
            title = "你输了"
        else:
            title = f"胜者：{name(winner_peer_id)}"
        ttk.Label(body, text=title, style="Title.TLabel").pack(anchor=tk.W)
        
        # 根据角色显示不同提示
        is_host = self.role == "host"
        is_player = self.role in ("host", "player2")
        if is_host:
            hint_text = "你可以选择再来一局或返回大厅。"
        elif self.role == "player2":
            hint_text = "你可以选择再来一局（需重新准备）或返回大厅。"
        else:
            hint_text = "你可以返回大厅。"
        ttk.Label(body, text=hint_text, style="Hint.TLabel").pack(anchor=tk.W, pady=(8, 14))

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill=tk.X)

        def back_to_lobby() -> None:
            """返回大厅"""
            win.destroy()
            self._back()

        def play_again() -> None:
            """再来一局"""
            win.destroy()
            room_id = self.room_id
            if not room_id:
                return
            if is_host:
                # 房主：重置游戏状态，等待玩家准备
                self.app.core.reset_game(room_id)
            else:
                # 玩家2：重置本地准备状态，等待房主开始
                self._ready_state = False
                if hasattr(self.app, "_sync_game_header_actions"):
                    try:
                        getattr(self.app, "_sync_game_header_actions")()
                    except Exception:
                        pass

        # 玩家（房主和玩家2）显示两个按钮，观战者只显示返回大厅
        if is_player:
            ttk.Button(btns, text="再来一局", style="Primary.TButton", command=play_again).pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Button(btns, text="返回大厅", command=back_to_lobby).pack(side=tk.RIGHT)

        win.update_idletasks()
        root = self.winfo_toplevel()
        root.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        root_width = root.winfo_width()
        root_height = root.winfo_height()
        root_x = root.winfo_rootx()
        root_y = root.winfo_rooty()
        x = root_x + (root_width - width) // 2
        y = root_y + (root_height - height) // 2
        win.geometry(f"{width}x{height}+{x}+{y}")
