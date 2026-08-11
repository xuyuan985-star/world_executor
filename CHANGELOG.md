# 变更日志（Bug 479/480）

版本规则：SemVer（Bug 478）——主版本.次版本.修订
- 主版本：破坏性变更（知识包 schema / 执行协议不兼容）
- 次版本：新功能（向后兼容）
- 修订：bug 修复

## [0.6.0] - 2026-08-11（任务中心回滚：进程内集成 → QProcess 子进程 + 项目内 m7/）

### 决策背景
0.5.0 的 m7 任务中心进程内集成（QThread `import main` 同进程）在真实环境
反复 0xC0000409 崩溃（Qt 析构运行中 QThread——m7 设计为独立进程程序，
塞进 GUI 进程违反其架构假设）。多轮排查（探针实证）确认结构性根因后，
**回滚为 QProcess 子进程模式**（m7 官方同款运行方式），同时保持 m7 源码
**在项目内 `m7/`**（自包含、随项目分发、打包方便）。

### 架构（回滚后）
- 任务中心：QProcess 启动 `m7_venv\Scripts\python.exe -u m7_launcher.py <task>`
  → m7_launcher 注入 pylnk3 stub → runpy 跑项目内 m7/main.py
- m7 在**独立进程**跑：cwd/单例/配置/Qt 全局状态零冲突——m7 崩了只是
  子进程崩，GUI 毫发无损（0xC0000409 结构性消失）
- 停止 = TerminateProcess（kill 即停——进程内模式只能"标记等自然结束"）
- 日志 = QProcess 管道 readyRead 实时（进程内模式曾因 stderr 重定向憋住）
- m7 源码：项目内 `m7/`（主路径，gitignore 不入库；setup_m7 克隆官方仓库）；
  旧外部 `March7thAssistant` 仅作更新镜像/兜底
- 宝箱收集链（自研 win_capture/ocr_engine/template_backend/win32_backend）
  **不受影响，保留**

### 变更文件
- `gui/tasks/runner.py`：QThread 进程内版 → QProcess 子进程版（恢复
  faf7608^ 设计：管理员 fail-closed、PYTHONUTF8、-u 管道日志）
- `gui/tasks/m7_launcher.py`：恢复（pylnk3 stub + runpy），M7 指向项目内 m7/
- `gui/tasks/catalog.py`：M7_ROOT 主路径 = 项目内 m7/（含 _FROZEN exe 分支）
- `gui/tasks/m7_updater.py`：重写——项目内 m7/ 运行时副本 + 外部镜像
  更新源（git pull → _sync_to_runtime robocopy 同步，排除 config.yaml）
- `gui/pages/placeholder.py`：TaskCenterPage 恢复子进程版（无 poll/探针），
  shutdown 修正 waitFinished → waitForFinished
- `gui/main_window.py`：closeEvent 恢复简单 stop+wait（kill 即停，无
  os._exit 兜底）；保留 HealthWorker 退出注册 + 窗口自愈
- `gui/run.py`：删除进程内集成专用探针（quit/hide/nativeEvent
  monkeypatch）；退出保护改 all_running_qthreads（HealthWorker）
- `tests/gui/test_runner_lifecycle.py`：重写为 QProcess 版（fail-closed/
  stop 安全/初始状态）

### 验证
- m7_launcher 子进程链路冒烟：`python -u gui/tasks/m7_launcher.py --list`
  退出 0、正确列出任务（stub + 项目内 m7/ + main.py 全通）
- tests/gui 6 项全 PASS；run_gate 10 项全 PASS

## [0.5.1] - 2026-08-11（任务中心闪退修复：QThread 生命周期 + 日志实时化）

### 根因（WER 实锤）
任务中心点开始后无反馈 → 关窗口即闪退。三个问题叠加：
1. **closeEvent task_pending 判断方向反了（本次根因，探针实证）**：
   `task_pending = self.studio.shutdown() is False`——shutdown 返回
   False 是"干净结束"，`False is False` 恒 True → **无任务关窗口也
   os._exit(0) 无痕退出**（用户感知"窗口消失"）；而任务真卡住时返回
   True → `True is False` 恒 False → 不兜底 → 正常析构运行中 QThread
   → Qt6Core qFatal 0xC0000409（WER 14:38/14:43 实锤）。
   修复：`task_pending = bool(self.studio.shutdown())`（True=任务在跑→兜底）
2. **0xC0000409 崩溃**：任务线程仍在运行时销毁 QThread 对象 → Qt6Core
   qFatal "QThread destroyed while running" → 进程直接退出（最小复现：
   deleteLater 运行中 QThread → 3s 即死）
3. **日志被全局憋住**：`_TaskThread.run()` 把进程级 `sys.stderr` 换成
   StringIO，日志要等 run_sub_task 返回才 drain——m7 任务卡在等游戏窗口
   （`wait_until(switch_to_game, 360)` 最长 360s）期间界面零反馈

### 修复
- `gui/main_window.py`：closeEvent task_pending 判断修正（`is False` → `bool()`）
- `gui/tasks/runner.py`：
  - 日志改 `_TeeStream` 双写流：m7 stderr 实时转发到日志队列 + 旧 stderr
    （200ms 轮询立即可见，不再等任务结束）
  - `TaskProcess.shutdown()`：wait 超时后 `setParent(None)` 摘链 + 模块级
    孤儿表 `_ORPHAN_THREADS` 持有引用 + `finished → deleteLater`——父对象
    销毁不再连带销毁运行中 QThread；返回 False 表示任务仍在运行
  - `_ACTIVE_THREADS` 活动线程注册表 + `active_task_threads()`（退出保护用）
- `gui/run.py`：`app.exec()` 返回后退出保护——任务线程仍在运行 →
  `os._exit(0)` 跳过 Qt 析构（防 0xC0000409）；退出路径探针
  （aboutToQuit 全线程栈 dump、app.quit/exit monkeypatch 调用栈、
  MainWindow destroyed 记录、atexit 记录）
- `app/__main__.py`：faulthandler（SIGSEGV 全线程栈落盘）+ 线程异常钩子
  + atexit 退出探针（区分正常退出 vs os._exit/崩溃）
- `gui/pages/placeholder.py`：`TaskCenterPage.shutdown()` 返回任务状态
- `gui/run.py`：`_install_excepthook` 日志级别 ERROR → INFO（任务日志落盘）
- 新增 `tests/gui/test_runner_lifecycle.py`（QThread 摘链不崩 2 项）+
  `tests/gui/test_close_pending.py`（closeEvent 判断语义 3 项）

### 验证
- 探针实证：无任务关窗口 → closeEvent accepted 正常退出（修复前 os._exit）；
  任务卡住关窗口 → 8s 等待后 os._exit(0)（修复前 0xC0000409 崩溃）
- 生命周期最小复现（旧代码 0xC0000409 闪退）→ 修复后 deleteLater 不崩
- 日志实时性：fake 任务每步日志 0.2s 内显示（旧实现任务结束才显示）
- run_gate 10 项全 PASS；tests/gui 5 项全 PASS

## [0.5.0] - 2026-08-11（数据内化：运行时零依赖 March7thAssistant）

### 架构变更（用户要求：m7 代码是参考，功能必须内化而非"套壳"引用）
- **宝箱收集链全自研**（`runtime/drivers/march7th/` 仅剩类名，实现全自研）：
  - 截图：`runtime/win_capture`（PrintWindow 后台 → 前台 mss 兜底）
  - OCR：新建 `runtime/ocr_engine.py`（rapidocr 直连，适配 RapidOCROutput 新 API）
  - 模板匹配：`runtime/input/template_backend`（cv2 多尺度）
  - 输入：`runtime/input/win32_backend`（SendInput）
  - 文本点击：自研 OCR 定位 + 点击（替代 m7 click_element）
  - 窗口：`runtime/win_capture` 自研枚举/激活
- **任务中心 m7 源码迁入项目** `m7/`（66.8MB，gitignore 不入库）——
  catalog.M7_ROOT 主路径改项目内，旧外部位置兜底；runner `import main` 从项目内
- **Fhoe 地图传送资产内化**：368 图拷入 `assets/fhoe/`
- **game_launcher**：config.yaml 读项目内 `m7/`
- 外部 `March7thAssistant` 目录实测删除后全链路可用（2026-08-11 改名验证）

### 修复
- run_gate unit/architecture 扫描跳过列表补 `m7`/`m7_venv`（数千第三方文件
  被 AST 遍历导致门禁慢到像卡死）

### 验证
- 外部 m7 删除模拟：March7thVision/输入后端/MainWindow/任务中心路径全 OK
- run_gate 10 项全 PASS（architecture/security/unit/replay/gate/guard/planner/
  smoke/pipeline/dry_run）
- 自研 OCR 实测识别 + 归一化合并正常

## [0.4.1] - 2026-08-11（10 波全量化修复）

### 执行链（runtime）
- 遇怪循环中断检查失效（`_interruptible_wait(0)` 恒 True → stop/emergency 被忽略），改为检查 3s 等待返回值
- `_step_portal` 用 `ok is True` 判断 ExecutionResult 对象恒 False——永久失败（缺验证模板）被误标可重试且丢错误信息，改为 isinstance 透传原结果
- VisionGate OCR-only 退化公式 `OCR_WEIGHT*ocr/OCR_WEIGHT*0.55` 乘除抵消，简化为 `ocr*0.55`
- `VisionGate.validate()` 补齐 `mode`/`score` 返回键——orchestrator 的 observe 降级分支（OCR 强 VLM 弱 → 观察不执行）从死代码激活

### GUI
- 指挥台 `_status_color` 颜色表键是 succeeded/interrupted，runtime 实际发 done → 完成目标永远灰色；统一查 STATUS_COLOR
- 世界图"执行此区域"区域匹配 bug：combo payload 中文名 vs 世界图英文 id 恒不匹配，实际跑"全部目标"；改 `find_region_index` 反查 + 直接执行 matched
- `_start_run` 防重入状态集补 `paused`（暂停后无法恢复）+ state 枚举/字符串归一化
- `command_deck.led` 无保护访问（error_page 兜底页无 led，热键线程 AttributeError）——全访问点 `_deck()` 判空
- 导航 56px 图标条补 tooltip（addSubInterface 返回 item.setToolTip）

### 跨线程（本环境 Qt 跨线程信号不可靠）
- 主事件链 `event_received` 信号 → 改线程安全队列 + 50ms QTimer 轮询消费
- F10 热键 keyboard 回调线程 emit → 改入队 + QTimer 主线程 emit
- 关闭时 `GlobalHotkey.unregister_all()`（keyboard 钩子泄漏修复）

### 任务中心（m7 进程内集成）
- `_TaskThread.run()` 进程全局污染——sys.path/os.environ 只恢复 cwd，任务期间主线程 import/子进程受影响；finally 全量恢复
- Python 版本门槛 3.11+ → 3.12+（m7 PEP 701 语法，3.11 进程内 import main 会 SyntaxError）
- 删除死代码 `gui/tasks/m7_launcher.py`（子进程方案残留，无引用）+ no-op `task_finished.emit(0) if False else None`

### 工具层
- setup_m7: `py.split()` 空格拆断含空格路径 → `shlex.split`
- vlm_client: `getattr(settings,"VLM_RATE_PER_MIN",0)` 恒 0（模块无该属性，限流从未生效）→ `settings.get()`
- run_pipeline: 多视频帧名 f_%04d 碰撞/目录被后视频清空 → 每视频独立帧子目录 + 视频内裁剪 + 模板名前缀
- verify_points: 正则无守卫 AttributeError + total_real=0 除零
- validate_all: `--report` 尾参 IndexError
- sendinput_probe: dwExtraInfo POINTER(c_ulong) → c_size_t（CLAUDE.md 教训重犯）
- input_privilege_check: GetTokenInformation 缓冲 16 字节装不下 SID（恒 LOW）→ 两段式缓冲 + 查返回值
- windows_stability_test: shot None 时 dark/var UnboundLocalError
- sync_chest_registry: verify.ocr 为 dict 时 KeyError，兼容 list/dict

### 基线门禁修复（run_gate 此前红）
- architecture_check: IGNORE_DIRS 漏 m7_venv/build/dist → 依赖库 exec 被扫成违规
- game_launcher: `subprocess.call` + `shell=True`（lint 禁 + 注入面）→ Popen 参数化
- 知识包 portals.json: tp_herta_base from/to 引用不存在房间（dry_run FAIL）→ room_A→base_zone
- full_pipeline_test: StudioPage 已改名 TaskCenterPage（GUI 冒烟 ImportError）
- 删除空目录 knowledge/guides/maps/01_starlight_express（星穹列车无战利品已删，残留空目录致校验 FAIL）

### 死代码/硬编码清理
- theme: STATE_COLORS/#statusLedLabel/#stateLogView 死代码、Qt 未用导入
- run.py: map_name 硬编码"黑塔空间站" → 从攻略库 map.json 读（换地图分组名正确）
- review_templates: TEMPLATE_DIR 相对 cwd 硬编码 → __file__ 相对推导
- 未用导入清理：main_window/placeholder/guides_view/archive_video/capture_frames

### 验证
- `python tools/run_gate.py` 10 项全 PASS
- 额外 11 项测试全 PASS（planner×7 / knowledge / coords / config / vision-mask）

## [0.4.0] - 2026-08-10（当前主线）

### 新增
- 任务中心：m7 全部任务模块子进程执行（日常/体力/锄大地/模拟宇宙/差分/货币战争/挑战）+ 实时日志 + HUD 游戏内浮窗 + F10 联动停止 + "更新 m7 模块"（git pull + 依赖同步）
- m7 环境：m7_venv（Python 3.14 专用 venv）+ m7_launcher（pylnk3 stub 注入 + first_run 跳过）
- 坐标兜底：视频帧模板未命中 → 知识包归一化坐标点击（30 真点位实测帧模板全 <0.54）
- 差分验证：点击后画面变化检测 + nudge 微调重试（抄 GameCLI-Agent）
- 界面归一化：任务开始前 OCR 检测战斗/弹窗/菜单 → 自动退出到可执行画面（抄 m7 Screen）
- 三大策略：遇怪（auto/kill）、地图未解锁、机关检测
- 轨迹录制/回放：手动操作录制（WASD/视角/点击，归一化坐标分辨率自适应）→ 回放复现
- 地图传送：portal 步骤（打开地图 → 模板序列点击 Fhoe 资产 → 传送 → 加载等待）
- 地图集：网站真实战利品点位 1613 个（yxhhdl 逆向 categories.js + loc.js）→ 全区域骨架空位
- verify_points.py：网站数据 vs 本地覆盖率核查
- run_pipeline.py：一键预处理（视频 → 抽帧 → VLM → 裁剪 → 知识包）
- 完成状态自愈（QSettings 损坏值备份 + 重置）

### 修复
- HUD 日志跨线程信号不投递（轮询消费）；HUD 补启 + 订阅泄漏
- L0 光标探测抢鼠标（仅真机 gate 做）
- m7 日志 GBK 乱码（PYTHONUTF8 强制）
- win_capture UnboundLocalError（collect 内 import 遮蔽）
- 任务中心页面异常拉伸（setFixedHeight 动态高度）
- 完成状态永久报错（损坏值自愈）

## [0.3.0] - 2026-08-09（历史）

### 新增
- M1-A 真机闭环：截图 → 模板匹配（cv2 多尺度）→ SendInput 点击 → verify 验证
- GUI 完整重构：BasePage 统一框架、指挥台/攻略体系/观察中心/工作室/设置
- 统一入口 `python -m app`（GUI / --selftest / --gate / --cleanup）
- 知识管线：视频 → VLM → 点位自动归档（pending_review 复核链）
- 工具集：validate_all / autofix_points / migrate_points / cleanup_points / stress_test / full_pipeline_test
- CI：GitHub Actions（lint + tests + gate + compileall）

### 修复（审计轮 Bug 1-450）
- 输入链：SendInput 64 位结构修复、EmergencyMonitor 防自伤、Esc 安全停止热键
- 配置：默认值隔离、validate_config 范围校验、热重载、日志脱敏
- 数据：错误分类（损坏/重复/缺字段）、索引、迁移事务化、软删除
- 事件：订阅弱引用、异常隔离、50ms GUI 合并刷新
- 稳定性：重试指数退避、MAX_TARGET_ATTEMPTS、中断等待、资源统一管理

### 迁移说明（Bug 479）
- 新环境：`copy .env.example .env`（新增 TEMPLATE_THRESHOLD / VLM_RATE_PER_MIN 可选）
- 知识库：点位新增 coordinate_type/status/confidence/source_video 字段
  → 运行 `python tools/migrate_points.py` 自动迁移（旧数据自动兼容）
- 依赖：新增 opencv-python / mss / ruamel.yaml / PySide6（`pip install -r requirements.txt`）

## [0.2.0] - 早期（历史）

- 状态机执行器、orchestrator、vision gate、dry_run
- 攻略库体系（7 地图 / 69 区域 / 30 点位模板）
