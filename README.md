# WoozchLAN (Python 3.12)

一个基于 Tkinter 的局域网 P2P 五子棋桌面应用：即开即用、无需第三方依赖，同网段自动发现并建立点对点连接完成房间与对局同步。

**平台**：macOS、Windows（理论上 Linux 也可，只要 Python 带 Tk）

## 特性

- 局域网自动发现：UDP 广播在同网段发现同伴，零配置即可联机
- P2P 同步：TCP 连接同步房间与对局状态，消息以 JSON 帧传输
- 房主权威：棋盘计算与胜负判定在房主侧执行，支持观战
- 多实例支持：同机多开自动选择空闲端口，`profile` 隔离数据目录
- 持久化信息：昵称与 `peer_id` 保存在数据目录的 `settings.json`
- 纯标准库：不依赖任何第三方库，开箱即用

## 环境要求

- `Python 3.12`（或兼容版本），且包含 `Tkinter`（`_tkinter`）支持
- 同一局域网/子网（自动发现依赖广播），允许 UDP `37020` 与 TCP 临时端口通过防火墙

## 快速开始

```bash
python3.12 main.py
```

### 一键启动脚本

- macOS：双击 `run_mac.command`（或在终端运行 `bash run_mac.command`）
- Windows：双击 `run_windows.bat`

脚本均支持可选参数 `profile` 用于同机多开时隔离数据目录：

- macOS：`bash run_mac.command dev2`
- Windows：`run_windows.bat dev2`

若运行时提示缺少 `Tkinter/_tkinter`：请安装带 Tk 的 Python（Windows 安装向导中勾选 Tcl/Tk；macOS 可使用官方安装包或 Homebrew 的 `python-tk` 方案）。

同一台机器可同时启动多个实例，应用会自动选取空闲 TCP 端口并通过 UDP 广播加入网络。

## 配置与数据目录

- 环境变量：`GOMOKU_LAN_DATA_DIR` 可覆盖应用数据目录（便于多开或迁移数据）
- 默认数据目录：`~/.gomoku_lan`（按平台展开用户主目录）
- 持久化文件：`settings.json` 存储 `peer_id` 与昵称

参考实现：数据目录与设置读写逻辑见 [util.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/util.py) 与 [storage.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/storage.py)。

## 目录结构

```
.
├── main.py                      # 应用入口，启动 Tk 与核心
├── run_mac.command              # macOS 一键启动脚本（支持 profile）
├── run_windows.bat              # Windows 一键启动脚本（支持 profile）
├── gomoku_lan/
│   ├── app.py                   # run() 创建 GUI 根并挂载核心
│   ├── core.py                  # 房间/对局状态机与事件分发
│   ├── storage.py               # settings 持久化与多开锁
│   ├── util.py                  # 数据目录、ID、IP 相关工具
│   ├── gui/
│   │   ├── root.py              # Tk 窗口、事件处理与三大界面切换
│   │   ├── widgets.py           # 通用控件与样式
│   │   └── screens/
│   │       ├── lobby.py         # 大厅（房间列表）
│   │       ├── room.py          # 房间（准备/开始/退出）
│   │       └── game.py          # 对局（棋盘与落子）
│   └── net/
│       ├── discovery.py         # UDP 广播发现（端口 37020）
│       ├── node.py              # TCP 监听/连接，Peers 同步与消息路由
│       └── protocol.py          # JSON 帧编解码（4 字节长度前缀）
└── tests/
    ├── test_node.py             # 节点握手与 peers 同步
    ├── test_protocol.py         # 帧协议编解码
    ├── test_game.py             # 棋局逻辑与胜负判定
    └── test_storage.py          # 设置读写与锁机制
```

## 运行与架构说明

- 应用入口：`main.py` 调用 [app.run](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/app.py#L1-L14) 创建 Tk 窗口并挂载核心与界面
- GUI 驱动：界面事件通过 [gui/root.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/gui/root.py) 派发并响应核心事件
- 网络节点：
  - UDP 发现端口：`37020`，参见 [discovery.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/discovery.py#L12-L13)
  - TCP 监听：绑定到随机空闲端口（`bind('', 0)`），参见 [node.py:start](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/node.py#L55-L66)
  - 消息协议：JSON 帧 + 4 字节长度前缀，参见 [protocol.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/protocol.py)

## 测试

运行全部测试：

```bash
python -m unittest
```

或按文件运行，例如：

```bash
python tests/test_node.py
```

## 常见问题

- 缺少 Tkinter（`_tkinter`）：
  - Windows：安装 Python 3.12 并在安装向导中勾选 Tcl/Tk 组件
  - macOS：确保使用带 Tk 的官方 Python，或安装相应的 Tk 支持
- 找不到同伴/无法联机：
  - 确保设备处于同一子网，避免热点隔离
  - 放行 UDP `37020`、允许应用使用临时 TCP 端口
  - Windows 可能需要在首次运行时允许应用通过防火墙
- 多开昵称冲突：应用会为副本实例自动追加标识，避免 `peer_id` 冲突（文件锁机制）

## 许可证

暂未指定（发布到 GitHub 时可根据需要补充，如 MIT）。

## 致谢

感谢开源社区与 Python 标准库提供的稳健基础能力。

—— 项目关键文件：
- 入口与 GUI：[main.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/main.py)、[app.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/app.py)、[gui/root.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/gui/root.py)
- 核心与网络：[core.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/core.py)、[net/node.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/node.py)、[net/discovery.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/discovery.py)、[net/protocol.py](file:///Users/helchan/Space/HiProject/App/GomokuLAN/gomoku_lan/net/protocol.py)
