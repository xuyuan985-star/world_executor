# R4 GUI 层审查（2026-08-12）

## 结构（19 文件 4180 行）

| 文件 | 角色 |
|---|---|
| run.py | 启动链路（R1 已述）+ 退出保护三连 |
| main_window.py | MainWindow(FluentWindow) 869 行：导航 6 页 + HealthWorker + 事件轮询 + HUD/F10 + 关闭保护 |
| controllers/mission_controller.py | UI↔RuntimeAPI 业务封装 + 完成状态持久化 |
| pages/command_deck.py | 指挥台 593 行：目标树/运行状态/健康栏/FailureInspector |
| pages/guides_view.py | 世界图：地图浏览 + 自定义轨迹面板（勾选/删除/全选） |
| pages/placeholder.py | 748 行：TaskCenterPage/WorldGraphPage/ObservationPage/KnowledgePage/SettingsPage + error_page 兜底 |
| tasks/runner.py | TaskProcess（QProcess 子进程封装）+ QThread 注册表 |
| tasks/m7_launcher.py | 子进程启动器：pylnk3 stub 注入 + runpy 跑项目内 m7/main.py |
| tasks/catalog.py | 任务目录（12 任务 5 组）+ M7_ROOT/M7_PYTHON 路径推导（frozen/源码双场景） |
| overlay.py / hotkey.py / safe.py / theme.py | 游戏 HUD 层 / 全局热键 / gui_safe 装饰器 / 主题 |

## 核心机制

1. **跨线程通信策略（本环境实锤）**：QThread 信号 → QObject 槽**不投递**——所有跨线程结果走"属性 + 主线程 QTimer 轮询"：HealthWorker._result + _poll_health(500ms)；runner 事件 → deque 入队 + _poll_runtime_events(50ms) 消费。QProcess 是 Qt 原生异步（信号在 GUI 线程投递）——无此问题
2. **窗口自愈**：非关闭流程中主窗口不可见 → 500ms 内 show() 恢复（排除最小化/主动关闭）
3. **前台守护**：任务 running 期间 3s QTimer 拉游戏置顶 + HUD 补启 + reposition；失败/停止即停
4. **F10 紧急停止**：mission_controller.stop + 录制停止保存 + 任务中心子进程 kill + 兜底 keyup（WASD/Esc/Space/左右键）+ HUD 红色提示
5. **关闭链（closeEvent）**：标记 _we_closing → 录制收尾保存 → HealthWorker 中断 wait(3s) → 退订事件 → TaskCenterPage.shutdown（kill 子进程）→ shutdown()（保存几何/停 controller/bus.close/HUD destroy/热键 unhook）→ app.quit()
6. **完成状态持久化**：QSettings 单 key `mission_state:{pkg_key}`（sha256 前 12 位——地图隔离）+ version=3 + 损坏自愈（备份 sidecar）+ 未知目标告警；RLock 防重入
7. **任务中心**：TaskProcess 启动前强制管理员检查（m7 顶层 pyuac 提权会脱离 QProcess——fail-closed）；MARCH7TH_DOCKER_STARTED 跳过 first_run/pause；PYTHONUTF8 防 GBK 乱码；-u 防 stdout 缓冲；stop=kill（幂等中断安全）
8. **HUD 复用**：任务中心子进程日志实时转发到游戏内 HUD（append_external 线程安全入队）
9. **页面构造隔离**：_safe_page 单次尝试 → error_page（单页失败不拖垮主窗口）
10. **健康检测**：HealthWorker 启动 1 次 + 5s 周期刷新；结果 dict 校验（Bug 632）+ traceback 回传

## 可疑点（阶段二验证）

1. `_poll_health` 中 `getattr(w, "_result", None)` —— HealthWorker.run() 可能抛异常导致 `self._result` 未赋值？run() 里 except 分支赋值 ({}, traceback)——覆盖了。但 run() 里 `self._result = (result.get("capability", {}), "")` 之前的 `check_health()` 如果返回非 dict → raise RuntimeError → except 分支赋值。安全。
2. HealthWorker 复用：`_refresh_health` 5s 检查 isRunning 再 start()——但 HealthWorker 只能 start 一次？QThread 可以在 finished 后再次 start()。OK。
3. `ensure_hud()` 与 `_start_hud()` 存在重复注册路径——`if getattr(self, "_hotkeys", None) is None` 防重复；但 `self._hud = GameHudController(...)` 在 _start_hud 里无判空——若窗口存在且 _hud 已存在会重复创建覆盖？看 ensure_hud 有判空（`if getattr(self, "_hud", None) is not None: return`），但 _start_hud 没有。调用方 _ensure_game_foreground 有判空（`if getattr(self, "_hud", None) is None: self._start_hud(); return`）。但 start_foreground_watch → _start_hud 无判空——若已经通过 ensure_hud 建过 HUD，_start_hud 会再建一个？_start_hud 里 hotkeys 有判空但 _hud 没有 → **可能重复创建 GameHudController**（事件重复订阅 + 双窗口）。阶段二验证。
4. `TaskProcess._on_finished`：QProcess.kill 后 finished 信号带 -1？任务失败退出码判断 "负=被停止"——TaskCenterPage._on_finished 只显示退出码，无失败重试。OK 简单。
5. `MissionController._audit` 每次 start/stop 写日志——append-only，无轮转（长期运行日志增长，但用户操作频率低，可接受）
6. F10 里 `self.studio._proc` 直接访问私有属性——耦合但同包，可接受
