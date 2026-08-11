# R1 架构与数据流审查（2026-08-12）

## 分层总览

```
app/           入口：__main__（崩溃捕获/faulthandler/atexit 探针）→ launcher（参数路由）
gui/           PySide6 + qfluentwidgets：run.py（启动链路）→ MainWindow → pages/controllers/tasks
runtime/       业务核心（最大层，69 文件）：orchestrator/executor/输入/观察/决策/恢复
ingest/        离线管线：B 站视频下载 → 抽帧 → VLM 识别 → 点位/模板入库
knowledge/     数据：guides（地图/点位/区域）、source（知识包）、trajectories（录制轨迹）
config/        配置：.env + 运行时覆盖（线程安全）+ VLM API 配置
security/      quarantine 脱敏 + pylnk3 stub
tools/         门禁/校准/实机工具（24 个）
tests/         unittest + pytest（20+6 用例）
```

## 启动链路（gui/run.py）

1. 模块导入时设置 DPI RoundPreferFloor（必须在 QApplication 前）
2. `_install_excepthook`：全局异常 → 日志轮转（10MB×5）+ 脱敏 + 崩溃现场 dump（traceback/state/screenshot）
3. 单实例 QSharedMemory（失败等 4.5s 重试 → IPC 唤醒旧窗口）
4. `_elevate_if_needed`：非管理员自动 runas 提权（失败降级浏览模式）
5. `app.setQuitOnLastWindowClosed(False)`——显式接管关闭
6. 自定义地图同步：`custom_enabled_names()` → `sync_custom_map(enabled or None)`（空集=None 全量启用）
7. 加载所有地图目标（maps/*/map.json 读显示名，区域名映射）
8. `EventBus(persist)` + `RuntimeAPI(bus)` + `MainWindow(targets, bus, api)`
9. 退出保护三连：aboutToQuit / MainWindow.destroyed / app.exec() 返回后——有 QThread 存活就 `os._exit(0)` 跳过 Qt 析构（防 0xC0000409）

## 分层冻结规则（tools/architecture_check.py）

- FORBIDDEN：gui → runtime.step_executor/state_machine/events.schema/dry_run/observers/db；runtime → gui；observers → decision/step_executor/executor；decision → step_executor；step_executor → ingest.compiler
- 豁免：gui → runtime.api（唯一合法通道）
- runtime 核心禁 pyautogui/mss/pynput/mouse/keyboard（豁免 drivers/input/win_capture）
- 禁动态导入（import_module/__import__）、禁 exec/eval/compile/os.system/os.popen/subprocess.call/shell=True
- 忽略 m7/、m7_venv/、March7thAssistant/、tests/、build/ 等

## 事件系统（runtime/events/bus.py + schema.py）

- `WorldEvent`：type + execution_id + sequence_id + schema_version=1
- EVENT_TYPES 13 种（run_started/run_finished/state_changed/observation/action_executed/move_completed/vision_blocked/target_progress/fail_recorded/repair_recorded/pause_requested/resume_checked/human_intervention/deadlock_detected/verify_degraded/mission_summary）
- STATE_TYPES 11 种：INIT → CHECK_WORLD_STATE → NAVIGATING → PORTAL_TRANSITION(→FAILED) → VERIFYING → INTERACTING → EVENT_INTERRUPT / RECOVERING → DONE / ABORT
- 同步广播：内存 ring 5000 上限 + jsonl 20MB 轮转；订阅弱引用自动清理；订阅者异常隔离；`db.record_event` 落 sqlite
- 已知坑：mission_summary 曾漏注册导致 make_event 抛 ValueError

## 状态持久化（runtime/db.py）

- sqlite3 线程本地连接（WAL + synchronous=NORMAL + timeout=30）
- 表：progress（execution/target/room/status/时间戳）、events（事件审计）

## 配置（config/settings.py）

- .env 文件 + 环境变量 + 运行时覆盖三层（覆盖优先级最高，进程内生效不落盘）
- PyInstaller 兼容：sys._MEIPASS 时 ROOT 指向解包目录
- 关键项：qwen_api_key/base_url/model、default_map、knowledge_root、runtime_db_path、march7_root
- 日志脱敏：install_log_redaction（API key/cookie 不落盘）

## 知识数据（knowledge/）

- source/black_tower_test：知识包（chests.json/landmarks.json/portals.json/rooms.json/templates/workflows/package.json）
- guides/maps/：6 官方地图（02_herta 03_jarilo 04_xianzhou 05_penacony 06_amphoreus 07_dream_paradise）+ 08_custom（用户录制轨迹同步）
- guides_loader：load_guide_targets/load_guide_regions/sync_custom_map/custom_enabled_names

## 关键数据流

1. **宝箱收集**：CommandDeck 选目标 → MissionController.start → RuntimeAPI → WorkflowOrchestrator.run_target → 状态机（CHECK_WORLD_STATE→NAVIGATING→VERIFYING→INTERACTING→DONE）→ 截图/模板匹配/观察 → 决策层出 ActionIntent → 输入后端执行 → 事件回 GUI
2. **任务中心**：GUI → QProcess 起 m7_launcher.py → runpy 跑项目内 m7/main.py → 管道日志回 GUI
3. **录制→回放**：recorder（WASD/视角/点击/长按白名单）→ trajectories/*.json → sync_custom_map → 08_custom 点位 → 执行链 trajectory 步骤
4. **离线 ingest**：视频下载 → capture_frames 抽帧 → VLM 识别 → compiler/validate_graph → 点位/模板入 guides

## 观察到的架构特性

- 防御式编程密度极高：几乎每个函数都有"Bug NNN"注释（0-330+ 编号），异常路径普遍落盘
- 退出保护是核心关切（0xC0000409 反复出现）：三重保护 + 全线程栈 dump
- 输入链分层：drivers（March7th 适配，薄接口）→ input（win32_backend/template_backend/recorder/replayer）→ 上层只产 ActionIntent
- 门禁 10 项：architecture/security/units/replay/vision/guard/planner/smoke(SKIP)/pipeline/dry_run
