from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from collections import deque

from .. import __version__


class Toast:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._win: tk.Toplevel | None = None
        self._after: str | None = None

    def show(self, text: str, ms: int = 1800) -> None:
        if self._win is None or not self._win.winfo_exists():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#0b1220")
            self._win = win

            frame = ttk.Frame(win, style="Card.TFrame")
            frame.pack(fill=tk.BOTH, expand=True)
            self._label = ttk.Label(frame, text=text)
            self._label.pack(padx=14, pady=10)
        else:
            self._label.configure(text=text)

        self._reposition()
        if self._after is not None:
            self.root.after_cancel(self._after)
        self._after = self.root.after(ms, self._hide)

    def _reposition(self) -> None:
        if self._win is None:
            return
        self._win.update_idletasks()
        w = self._win.winfo_width()
        h = self._win.winfo_height()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        x = rx + (rw - w) // 2
        y = ry + rh - h - 34
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def _hide(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
        self._after = None


class StatusTicker(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, style="TFrame")
        self._queue: deque[str] = deque()
        self._text = ""
        self._text_id: int | None = None
        self._x = 0
        self._after: str | None = None

        # 左侧滚动消息区域
        self._canvas = tk.Canvas(
            self,
            bg="#0b1220",
            highlightthickness=0,
            bd=0,
            relief="flat",
            height=16,
        )
        self._canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), pady=0)
        self._canvas.bind("<Configure>", self._on_resize)

        # 右侧版本号标签
        self._version_label = ttk.Label(
            self,
            text=f"v{__version__}",
            style="Hint.TLabel",
            font=("Helvetica", 9),
            foreground="#64748b",
        )
        self._version_label.pack(side=tk.RIGHT, padx=(0, 10), pady=0)

    def push(self, text: str) -> None:
        t = text.strip()
        if not t:
            return
        self._queue.append(t)
        if self._after is None:
            self._start_next()

    def _on_resize(self, _ev: tk.Event) -> None:
        if self._text_id is None:
            return
        box = self._canvas.bbox(self._text_id)
        if not box:
            return
        canvas_w = self._canvas.winfo_width()
        text_w = box[2] - box[0]
        if self._x > canvas_w + text_w:
            self._start_next()

    def _start_next(self) -> None:
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        if not self._queue:
            self._text = ""
            if self._text_id is not None:
                self._canvas.itemconfigure(self._text_id, text="")
            return
        self._text = self._queue.popleft()
        if self._text_id is None:
            self._text_id = self._canvas.create_text(
                0,
                8,
                text=self._text,
                fill="#475569",
                anchor="w",
                font=("Helvetica", 10),
            )
        else:
            self._canvas.itemconfigure(self._text_id, text=self._text)
        self._x = -self._text_width()
        self._canvas.coords(self._text_id, self._x, 8)
        self._tick()

    def _text_width(self) -> int:
        if self._text_id is None:
            return 0
        box = self._canvas.bbox(self._text_id)
        if not box:
            return 0
        return max(0, box[2] - box[0])

    def _tick(self) -> None:
        if self._text_id is None:
            return
        text_w = self._text_width()
        canvas_w = self._canvas.winfo_width()
        self._x += 2
        self._canvas.coords(self._text_id, self._x, 8)
        if self._x > canvas_w:
            self._start_next()
            return
        self._after = self.after(24, self._tick)
