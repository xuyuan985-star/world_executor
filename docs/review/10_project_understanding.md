# R10 综合审查与《项目理解》（2026-08-12）

## 一句话概括

**WorldExecutor = 星穹铁道宝箱收集自动化（自研） + March7th 任务中心（QProcess 子进程复用）**，Windows/Python 3.14/PySide6，防御式编程密度极高（0-633 号 bug 注释贯穿全项目）。

## 全项目地图（147 文件 / 19253 行，不含 m7/）

```
┌─ app/（3 文件 206 行）──────────────────────────────┐
│  __main__: faulthandler/thread_excepthook/atexit 探针 │
│  launcher: --cleanup/--selftest/--gate/GUI 路由       │
└──────────────────────────────────────────────────────┘
┌─ gui/（19 文件 4180 行）────────────────────────────┐
│  run.py: DPI→单实例→提权→地图同步→MainWindow→退出三防 │
│  main_window: 6 页导航 + HealthWorker + 事件轮询 + HUD│
│  pages: 指挥台/世界图/观察中心/知识/任务中心/设置     │
│  tasks: QProcess 封装 + m7_launcher + catalog + 更新  │
│  controllers: MissionController（状态持久化）         │
└──────────────────────────────────────────────────────┘
┌─ runtime/（69 文件 8299 行）─────────────────────────┐
│  orchestrator: run_mission→run_target→步骤循环+状态机  │
│  step_executor: ActionIntent→guard→执行→diff 验证      │
│  input/: win32 后端 + 模板匹配 + 录制/回放闭环          │
│  events/: EventBus 同步广播 + jsonl 持久化             │
│  drivers/: March7th 薄适配（input/vision/window）      │
│  guards/decision/observers/recovery: 安全决策链        │
│  health/capability: G3 门槛 + 能力报告                 │
└──────────────────────────────────────────────────────┘
┌─ ingest/（10 文件 1571 行）── 离线视频→点位管线 ──────┐
│  bilibili 下载 → capture_frames 抽帧 → VLM 识别       │
│  → archive_video 归档点位 → compiler 校验             │
└──────────────────────────────────────────────────────┘
┌─ knowledge/ ── guides（6 官方图+08_custom）→source───┐
│  black_tower_test 知识包 + trajectories 录制轨迹      │
└──────────────────────────────────────────────────────┘
```

## 三大核心闭环

### 1. 宝箱收集闭环（自研主链）
```
指挥台选目标 → MissionController.start → RuntimeAPI(G3 门槛)
→ WorkflowOrchestrator.run_mission（前台守护/watchdog/遇怪策略）
→ 步骤循环（move/portal/trajectory/vgm/interact/verify）
→ 状态机（11 态）→ 失败分类（F1-F6）→ 完成状态持久化（pkg_key）
→ EventBus 事件 → GUI 轮询刷新
```
视觉链：截图（PrintWindow→mss）→ 模板匹配（cv2 21 级多尺度+sha256）→ OCR（rapidocr 直连）→ VLM（可熔断）→ VisionGate 双通道 → 决策（风险量化）→ ActionGuard → 输入（SendInput）

### 2. 录制→回放闭环（0.6.0 核心成果）
```
录制：pynput 钩子（白名单+诊断）→ 事件 JSON（归一化坐标/灵敏度）
→ trajectories/自定义-N.json → sync_custom_map → 08_custom 点位
→ 执行链 trajectory 步骤 → TrajectoryReplayer
→ mouse_event 真相对视角（≥8px 合并 + 0.3s 间隔）+ 分段等待 + 心跳
```

### 3. 任务中心闭环（QProcess 子进程）
```
TaskCenterPage → TaskProcess（管理员检查/env 注入）
→ m7_launcher（pylnk3 stub + runpy）→ 项目内 m7/main.py
→ 日志管道 → HUD 实时显示 → kill 即停
更新：UpdateProcess → git pull --ff-only → robocopy 同步 → 依赖过滤安装
```

## 全项目关键设计原则

1. **跨线程一律"入队+主线程轮询"**——QThread 信号→槽在本环境不投递（实锤）；QProcess 是 Qt 原生异步不受影响
2. **0xC0000409 退出保护三重门**——aboutToQuit/MainWindow.destroyed/app.exec 返回后，有 QThread 存活就 os._exit 跳过析构
3. **fail-closed 原则**——无法验证 = 失败（verify 模板缺失/无视觉通道/坐标越界都显式失败，绝不假成功）
4. **错误分类体系**——ErrorCode 枚举优先 + F1-F6 主类 + 子串兜底；retryable 由 PERMANENT_CODES 强制
5. **数据内化**——m7 源码进项目 m7/（66.8MB gitignore）；Fhoe 资产进 assets/fhoe/；零依赖外部目录
6. **隐私/安全**——pylnk3 stub（投毒包）、日志脱敏、报告 sanitize、单实例锁、IPC 唤醒、G3 权限门槛
7. **可复现性**——seed 由 execution_id 派生（sha256）；natural_mode=False 确定性；replay 回归

## 十轮审查累计可疑点（第二阶段验证清单）

| # | 可疑点 | 级别 | 来源 |
|---|---|---|---|
| 1 | `_current_target` 从未赋值——trajectory 事件 target 恒 None | 低 | R3 |
| 2 | `click_template` 重试耗尽 return None（调用方解包行为） | 中 | R2 |
| 3 | `_start_hud` 无 _hud 判空——可能重复创建 GameHudController | 中 | R4 |
| 4 | CircuitBreaker 半开仅 `__call__` 推进（allow 路径可能永不半开） | 中 | R6 |
| 5 | EventBus jsonl / FailureMemory 未脱敏（路径落盘） | 中 | R7 |
| 6 | git 泄露面核对（.gitignore 覆盖度） | 高 | R7/R19 |
| 7 | update_runner `.venv` 兜底路径死代码（.venv 已删） | 低 | R5 |
| 8 | `_step_portal` 返回 False 无 error/category 时分类模糊 | 低 | R3 |
| 9 | db.record_event 每事件 commit（性能） | 低 | R8 |
| 10 | guides map.json game_version=3.x vs 预期 2.x 每次告警 | 低 | R8 |
| 11 | replayer/recorder 无单测（核心机制靠实机） | 中 | R9 |
| 12 | EventBus 无独立单测（并发/弱引用/轮转） | 中 | R9 |

## 遗留待办（交接文档确认）

1. 实机验证视角回放（机制已修，等真机确认）
2. git 75 文件未提交（建议按模块分解提交）
3. 打包分发决策（m7/ 捆绑 or setup_m7.py 引导）
4. 骨架点位 x/y=null 补录；视频帧模板匹配率 58%
