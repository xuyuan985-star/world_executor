# 变更日志（Bug 479/480）

版本规则：SemVer（Bug 478）——主版本.次版本.修订
- 主版本：破坏性变更（知识包 schema / 执行协议不兼容）
- 次版本：新功能（向后兼容）
- 修订：bug 修复

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
