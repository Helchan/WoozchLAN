def run() -> None:
    from . import __version__
    from .util import acquire_instance_lock, release_instance_lock, get_app_root

    print(f"Heyou 游戏厅 v{__version__}")
    print("=" * 40)

    # 检查是否已有实例运行
    if not acquire_instance_lock():
        print(f"错误：程序已在运行中")
        print(f"程序目录: {get_app_root()}")
        print("如需多开，请复制整个程序目录后再启动")
        raise SystemExit(1)

    try:
        import tkinter as tk
    except ModuleNotFoundError as e:  # pragma: no cover
        release_instance_lock()
        raise SystemExit(
            "未检测到 tkinter（_tkinter）。请使用带 Tk 支持的 Python 3.12 安装，或在系统中安装 Tcl/Tk。"
        ) from e

    from .gui.root import RootWindow

    root = tk.Tk()
    app = RootWindow(root)
    app.start()
    
    try:
        root.mainloop()
    finally:
        release_instance_lock()
