# 变更日志（Bug 479/480）

版本规则：SemVer（Bug 478）——主版本.次版本.修订
- 主版本：破坏性变更（知识包 schema / 执行协议不兼容）
- 次版本：新功能（向后兼容）
- 修订：bug 修复

## [0.3.0] - 2026-08-09（当前主线）

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
