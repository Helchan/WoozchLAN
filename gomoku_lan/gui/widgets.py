from __future__ import annotations

import tkinter as tk
from tkinter import ttk


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

