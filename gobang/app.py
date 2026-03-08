def run() -> None:
    from . import __version__

    print(f"Heyou 游戏厅 v{__version__}")
    print("=" * 40)

    try:
        import tkinter as tk
    except ModuleNotFoundError as e:  # pragma: no cover
        raise SystemExit(
            "未检测到 tkinter（_tkinter）。请使用带 Tk 支持的 Python 3.12 安装，或在系统中安装 Tcl/Tk。"
        ) from e

    from .gui.root import RootWindow

    root = tk.Tk()
    app = RootWindow(root)
    app.start()
    root.mainloop()
