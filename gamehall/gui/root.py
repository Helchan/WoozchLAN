from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..core import Core, CoreEvent
from ..game import GameRegistry
from ..storage import (
    LocalNode,
    NetworkNode,
    load_settings,
    save_settings,
    init_local_node,
    ensure_local_node_in_network,
    generate_random_nickname,
)
from ..util import allocate_udp_port, guess_local_ip, new_id, now_ms
from .screens.game import GameScreen
from .screens.lobby import LobbyScreen
from .widgets import StatusTicker, Toast


class RootWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Heyou")
        self.root.geometry("1540x860")
        self.root.minsize(1540, 720)

        self._apply_theme()

        # 加载配置
        loaded_local, network_nodes = load_settings()
        current_ip = guess_local_ip()
        
        if loaded_local is None or loaded_local.ip != current_ip:
            # 新用户或 IP 变化：初始化本机节点
            local_node = init_local_node(current_ip)
        else:
            # 同一用户：保持 peer_id 和 nickname
            local_node = loaded_local
        
        # 分配 UDP 端口（从配置中的端口开始尝试）
        udp_port = allocate_udp_port(local_node.udp_port)
        if udp_port != local_node.udp_port:
            # 端口变化：说明是拷贝的程序目录，生成新的 peer_id 和 nickname
            # 这样不会覆盖原节点，而是作为新节点添加
            local_node = LocalNode(
                peer_id=new_id(),
                nickname=generate_random_nickname(),
                ip=current_ip,
                udp_port=udp_port,
            )
        elif local_node.ip != current_ip:
            local_node = LocalNode(
                peer_id=local_node.peer_id,
                nickname=local_node.nickname,
                ip=current_ip,
                udp_port=local_node.udp_port,
            )
        
        # 确保 local_node 在 network_nodes 中
        network_nodes = ensure_local_node_in_network(local_node, network_nodes)
        
        # 保存配置
        save_settings(local_node, network_nodes)
        
        self._local_node = local_node
        self._network_nodes = network_nodes

        # 创建 NodeConfig
        from ..net.node import NodeConfig
        node_cfg = NodeConfig(
            peer_id=local_node.peer_id,
            nickname=local_node.nickname,
            ip=local_node.ip,
            udp_port=local_node.udp_port,
            network_nodes=network_nodes,
        )
        self.core = Core(
            node_cfg=node_cfg,
            local_node=local_node,
            network_nodes=network_nodes,
            on_event=self._on_core_event,
        )

        self._header = ttk.Frame(self.root)
        self._header.pack(fill=tk.X, padx=18, pady=(18, 12))

        self._title = ttk.Label(self._header, text="Heyou游戏厅", style="Title.TLabel")
        self._title.pack(side=tk.LEFT)

        self._sub = ttk.Label(self._header, text="LAN • P2P • 即开即用", style="SubTitle.TLabel")
        self._sub.pack(side=tk.LEFT, padx=(10, 0), pady=(6, 0))

        # 大厅操作按钮和昵称控件的回调（由 lobby 屏幕调用）
        self._nick_var = tk.StringVar(value=self.core.nickname)

        self._game_actions = ttk.Frame(self._header)
        self._game_ready_btn = ttk.Button(self._game_actions, text="准备", style="Primary.TButton", command=self._on_header_ready)
        # 不在这里 pack，由 _sync_game_header_actions 控制
        self._game_start_btn = ttk.Button(self._game_actions, text="开始对战", style="Primary.TButton", command=self._on_header_start)
        # 不在这里 pack，由 _sync_game_header_actions 控制
        self._game_back_btn = ttk.Button(self._game_actions, text="返回大厅", command=self._on_header_back)
        self._game_back_btn.pack(side=tk.LEFT)

        self._content = ttk.Frame(self.root)
        self._content.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 8))

        self.screens: dict[str, ttk.Frame] = {}
        self.screens["lobby"] = LobbyScreen(self._content, self)
        self.screens["game"] = GameScreen(self._content, self)

        for s in self.screens.values():
            s.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._status_ticker = StatusTicker(self.root)
        self._status_ticker.pack(fill=tk.X, padx=18, pady=(0, 6))

        self.toast = Toast(self.root)
        self._current = "lobby"
        self._room_role_by_id: dict[str, str] = {}
        self._room_chat: dict[str, list[dict[str, str]]] = {}
        self._room_participants_by_id: dict[str, object] = {}
        self._peer_nicknames: dict[str, str] = {}
        self._peer_inited = False

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
        self._refresh_top_title(name, kwargs)
        self._sync_game_header_actions()

    def _refresh_top_title(self, screen: str, kwargs: dict[str, object]) -> None:
        if screen == "lobby":
            self._title.configure(text="Heyou游戏厅")
            self._sub.configure(text="LAN • P2P • 即开即用")
            return
        rid = str(kwargs.get("room_id", ""))
        room = self.core.rooms.get(rid) if rid else None
        game = str(getattr(room, "game", "gobang")) if room is not None else "gobang"
        handler = GameRegistry.get_handler(game)
        game_name = handler.get_config().game_display_name if handler else game
        self._title.configure(text=game_name)
        self._sub.configure(text="")

    def _sync_game_header_actions(self) -> None:
        lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
        if self._current == "lobby":
            if self._game_actions.winfo_manager():
                self._game_actions.pack_forget()
            self._sync_lobby_header_actions()
            return
        # 非大厅界面时，隐藏 lobby 的按钮
        lobby.hide_actions()
        if self._current != "game":
            if self._game_actions.winfo_manager():
                self._game_actions.pack_forget()
            return
        if not self._game_actions.winfo_manager():
            self._game_actions.pack(side=tk.RIGHT)
        game: GameScreen = self.screens["game"]  # type: ignore[assignment]
        
        # 检查游戏是否正在进行中
        game_in_progress = False
        if game.room_id:
            game_obj = getattr(self.core, "_games", {}).get(game.room_id)
            game_in_progress = game_obj is not None
        
        if game.role == "host":
            # 房主：只显示"开始对战"按钮
            if self._game_ready_btn.winfo_manager():
                self._game_ready_btn.pack_forget()
            if not self._game_start_btn.winfo_manager():
                self._game_start_btn.pack(side=tk.LEFT, padx=(0, 10), before=self._game_back_btn)
            if game_in_progress:
                # 游戏进行中：显示灰色"对战中"
                self._game_start_btn.configure(text="对战中", state=tk.DISABLED)
            else:
                # 等待中：根据条件启用/禁用"开始对战"
                state = tk.NORMAL if game.can_start_game() else tk.DISABLED
                self._game_start_btn.configure(text="开始对战", state=state)
        elif game.role == "player2":
            # 玩家二：只显示"准备"按钮
            if self._game_start_btn.winfo_manager():
                self._game_start_btn.pack_forget()
            if not self._game_ready_btn.winfo_manager():
                self._game_ready_btn.pack(side=tk.LEFT, padx=(0, 10), before=self._game_back_btn)
            if game_in_progress:
                # 游戏进行中：显示灰色"对战中"
                self._game_ready_btn.configure(text="对战中", state=tk.DISABLED)
            else:
                # 等待中：显示"准备"/"取消准备"
                self._game_ready_btn.configure(text=game.ready_button_text(), state=tk.NORMAL)
        else:
            # 观战者：隐藏所有操作按钮
            if self._game_ready_btn.winfo_manager():
                self._game_ready_btn.pack_forget()
            if self._game_start_btn.winfo_manager():
                self._game_start_btn.pack_forget()

    def _sync_lobby_header_actions(self) -> None:
        if self._current != "lobby":
            return
        lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
        can_join = lobby.can_join_selected()
        can_watch = lobby.can_watch_selected()
        lobby.set_join_button_state(tk.NORMAL if can_join else tk.DISABLED)
        lobby.set_watch_button_state(tk.NORMAL if can_watch else tk.DISABLED)

    def _commit_nickname(self) -> None:
        if self._current != "lobby":
            self.toast.show("仅可在大厅修改昵称")
            return
        nick = self._nick_var.get().strip()
        if not nick:
            return
        self._nick_var.set(nick)
        self.core.set_nickname(nick)
        
        # 更新本地节点信息并保存
        self._local_node = LocalNode(
            peer_id=self._local_node.peer_id,
            nickname=nick,
            ip=self._local_node.ip,
            udp_port=self._local_node.udp_port,
        )
        # 更新 network_nodes 中的本机节点
        self._network_nodes = ensure_local_node_in_network(self._local_node, self._network_nodes)
        save_settings(self._local_node, self._network_nodes)
        self.toast.show("昵称已更新")

    def _on_header_ready(self) -> None:
        if self._current != "game":
            return
        game: GameScreen = self.screens["game"]  # type: ignore[assignment]
        game._toggle_ready()

    def _on_header_start(self) -> None:
        if self._current != "game":
            return
        game: GameScreen = self.screens["game"]  # type: ignore[assignment]
        game._start()

    def _on_header_back(self) -> None:
        if self._current != "game":
            self.show("lobby")
            return
        game: GameScreen = self.screens["game"]  # type: ignore[assignment]
        game._back()

    def _show_room_closed_alert(self, message: str) -> None:
        """显示房间关闭弹窗，关闭后返回大厅"""
        win = tk.Toplevel(self.root)
        win.title("房间已关闭")
        win.configure(bg="#0b1220")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        body = ttk.Frame(win, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(body, text=message, style="TLabel", wraplength=300).pack(pady=(0, 16))

        def on_close() -> None:
            win.destroy()
            self.show("lobby")

        ttk.Button(body, text="返回大厅", style="Primary.TButton", command=on_close).pack()

        # 居中显示
        win.update_idletasks()
        w = win.winfo_width()
        h = win.winfo_height()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        win.geometry(f"+{x}+{y}")

        win.protocol("WM_DELETE_WINDOW", on_close)

    def _show_opponent_left_alert(self, message: str) -> None:
        """显示对手退出弹窗（房主看到），关闭后留在房间"""
        # 先刷新游戏界面（确保棋盘重置）
        if self._current == "game":
            game: GameScreen = self.screens["game"]  # type: ignore[assignment]
            game.refresh()
            self._sync_game_header_actions()
            self.root.update_idletasks()  # 强制更新 UI
        
        win = tk.Toplevel(self.root)
        win.title("对手已退出")
        win.configure(bg="#0b1220")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        body = ttk.Frame(win, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(body, text=message, style="TLabel", wraplength=300).pack(pady=(0, 16))

        def on_close() -> None:
            win.destroy()

        ttk.Button(body, text="确定", style="Primary.TButton", command=on_close).pack()

        # 居中显示
        win.update_idletasks()
        w = win.winfo_width()
        h = win.winfo_height()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        win.geometry(f"+{x}+{y}")

        win.protocol("WM_DELETE_WINDOW", on_close)

    def _on_core_event(self, ev: CoreEvent) -> None:
        self.root.after(0, lambda: self._on_core_event_ui(ev))

    def _on_core_event_ui(self, ev: CoreEvent) -> None:
        if ev.type == "node":
            return
        if ev.type == "peers":
            items = ev.payload.get("items", [])
            self._update_status_by_peers(items)
            lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
            lobby.set_peers(items)
            return
        if ev.type == "nickname_changed":
            nick = str(ev.payload.get("nickname", "")) or self.core.nickname
            self._nick_var.set(nick)
            return
        if ev.type == "rooms":
            now = now_ms()
            if now - self._last_rooms_refresh_ms < 120:
                return
            self._last_rooms_refresh_ms = now
            lobby: LobbyScreen = self.screens["lobby"]  # type: ignore[assignment]
            lobby.set_rooms(list(self.core.rooms.values()))
            if self._current == "game":
                game: GameScreen = self.screens["game"]  # type: ignore[assignment]
                self._refresh_top_title("game", {"room_id": game.room_id or ""})
                self._sync_game_header_actions()
            return
        if ev.type == "room_entered":
            rid = str(ev.payload.get("room_id", ""))
            role = str(ev.payload.get("role", "spectator"))
            if rid:
                self._room_role_by_id[rid] = role
                self._room_chat.setdefault(rid, [])
                participants = ev.payload.get("participants")
                if participants is not None:
                    self._room_participants_by_id[rid] = participants
            if rid:
                payload = dict(ev.payload)
                if "participants" not in payload:
                    payload["participants"] = self._room_participants_by_id.get(rid)
                self.show("game", **payload)
            else:
                self.show("lobby")
            return
        if ev.type == "room_left":
            rid = str(ev.payload.get("room_id", ""))
            if rid:
                self._room_role_by_id.pop(rid, None)
                self._room_chat.pop(rid, None)
                self._room_participants_by_id.pop(rid, None)
            self.show("lobby")
            return
        if ev.type == "room_closed_alert":
            rid = str(ev.payload.get("room_id", ""))
            message = str(ev.payload.get("message", "")) or "房间已关闭"
            if rid:
                self._room_role_by_id.pop(rid, None)
                self._room_chat.pop(rid, None)
                self._room_participants_by_id.pop(rid, None)
            # 显示弹窗提醒，关闭后返回大厅
            self._show_room_closed_alert(message)
            return
        if ev.type == "opponent_left_alert":
            # B 方全部退出时的弹窗提示（房主看到）
            message = str(ev.payload.get("message", "")) or "对手已退出"
            self._show_opponent_left_alert(message)
            return
        if ev.type == "room_state":
            rid = str(ev.payload.get("room_id", ""))
            participants = ev.payload.get("participants")
            if rid and participants is not None:
                self._room_participants_by_id[rid] = participants
            if self._current == "game":
                game: GameScreen = self.screens["game"]  # type: ignore[assignment]
                if game.room_id and game.room_id == rid:
                    game.update_participants(participants)
                self._sync_game_header_actions()
            return
        if ev.type == "toast":
            self.toast.show(str(ev.payload.get("text", "")) or "提示")
            return
        if ev.type == "game_started":
            # 保留当前的 role，不要被重置为 spectator
            rid = str(ev.payload.get("room_id", ""))
            payload = dict(ev.payload)
            if rid and rid in self._room_role_by_id:
                payload["role"] = self._room_role_by_id[rid]
            self.show("game", **payload)
            return
        if ev.type == "game_state":
            game: GameScreen = self.screens["game"]  # type: ignore[assignment]
            if self._current == "game":
                game.refresh()
                self._sync_game_header_actions()
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
                if self._current == "game":
                    game: GameScreen = self.screens["game"]  # type: ignore[assignment]
                    game.refresh_chat()
            return

    def _update_status_by_peers(self, items: object) -> None:
        if not isinstance(items, list):
            return
        current: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("peer_id", ""))
            if not pid or pid == self.core.peer_id:
                continue
            nick = str(item.get("nickname", "")).strip() or pid[:6]
            current[pid] = nick
        if not self._peer_inited:
            self._peer_nicknames = current
            self._peer_inited = True
            return
        prev = self._peer_nicknames
        joined = [pid for pid in current if pid not in prev]
        left = [pid for pid in prev if pid not in current]
        for pid in joined:
            self._status_ticker.push(f"{current.get(pid, pid[:6])} 上线了")
        for pid in left:
            self._status_ticker.push(f"{prev.get(pid, pid[:6])} 下线了")
        self._peer_nicknames = current

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
        # 面板内紧凑型按钮样式
        style.configure(
            "Small.TButton",
            padding=(8, 3),
            font=("Helvetica", 11),
            background=border,
            foreground=fg,
        )
        style.map(
            "Small.TButton",
            background=[("active", "#243252")],
        )
        style.configure(
            "SmallPrimary.TButton",
            padding=(8, 3),
            font=("Helvetica", 11),
            background=accent,
            foreground="#052e16",
        )
        style.map(
            "SmallPrimary.TButton",
            background=[("active", "#16a34a"), ("disabled", "#14532d")],
        )
        style.configure(
            "Nick.TEntry",
            padding=(10, 8),
            fieldbackground=panel,
            foreground=fg,
            insertcolor=fg,
        )
        # 面板内紧凑型输入框样式
        style.configure(
            "SmallNick.TEntry",
            padding=(6, 3),
            font=("Helvetica", 11),
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
