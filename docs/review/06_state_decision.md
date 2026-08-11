# R6 状态与决策层审查（2026-08-12）

## 安全（safety.py — EmergencyMonitor）

- daemon 线程 0.5s 轮询：光标移动（>30px 半径）/ 前台切换 / Esc 热键（防抖动 2s）→ human_intervention + pause_requested
- `_paused=True` 后停止触发（is_paused 供 orchestrator 检查）；resume() 重置光标基准
- suspend_mouse/resume_mouse：机器人自身输入期间挂起光标检测（自伤防护）；resume 时重设基准（点击后光标停在目标处）
- 权限边界明确：只监控光标/前台，不监控键盘输入

## 观察存储（observation_store.py）

- ObservationRecord：bbox/timestamp/confidence/frame_id；is_stale(1.5s)
- set() 结构校验（2 中心点/4 角点、[0,1] 越界拒绝——clamp 会点错对象）
- 容量 64 + 受保护 id 不淘汰（BUG-073）；get() 返回不可变快照
- get_valid()：统一有效观测入口（时效+置信内置，业务层禁止绕过）

## 世界状态（world_state.py）

- room/ui/completed/confidence；update() 事件化变更（E9 禁止直接改）；confidence 取 max

## 熔断器（circuit_breaker.py）

- 三态 CLOSED→OPEN→HALF_OPEN；failure_threshold=3、cooldown=30s；VLM_BREAKER 全局单例
- 注意：`_tick_half_open` 只在 `__call__` 装饰器路径推进；`allow()` 不推进——潜在半开永远不触发？（阶段二验证：VLM 调用路径是否用 __call__）

## 安全闸门（guards/action_guard.py + policy.py + risk.py）

- check()：动态风险计算（视觉未确认 +50 / VLM 单高置信幻觉 +40 / 危险动作 +30 / 证据过期 +10）→ risk 等级（critical≥70 / high≥40 / medium≥20）→ 声明等级取更严 → critical 拒绝自动执行
- 证据校验：expired（>3s，高风险 1.5s）→ VISION_EXPIRED；置信门槛（high 需 0.85 双通道）
- strict=False 兼容模式：未验证意图放行（workflow 模板路径自带 verify 闭环）
- Policy：purchase/delete/confirm/exit 风险 <10；click/click_text <30；其他 <60

## 失败记忆与恢复（failure_memory / failure_report / recovery/manager）

- FailureMemory：jsonl 追加 + 线程锁单行原子写；query 按 failure 子串/target 过滤
- FailureReporter：时间戳目录（截图 + report.json + environment.json）；sanitize_mapping 脱敏
- RecoveryManager：CAPTURE_FAIL → 重试×3（退避）→ WINDOW_RECOVERY → STOP

## 视觉门（vision_gate.py 268 行）

- VisionEvidence（ocr/vlm/frame_quality）→ evaluate：双通道评分（阈值 0.75 / ocr_only 0.5）→ 决策（trusted/untrusted/observe 模式）
- validate()：观察模式放行重试、untrusted 拒绝 + 决策快照 dump_vision_decision
- orchestrator.observe_act：gate 不信任 → 观察模式/拒绝执行（F4_VISION + vision_blocked 事件）

## 观察器（vision_observer.py + observers/vlm_vision.py）

- OCRAdapter + VisionObserver + fuse_observation（OCR/VLM 融合）
- validate_vlm_output：locate/room 输出 schema 校验（found/xy/confidence）
- VLM 观察器：截图 → VLM API → 结构化输出

## March7thVision 驱动（drivers/march7th/vision.py 305 行）

- VisionInterface ABC：screenshot_path/take_screenshot/ocr_lines/find_template/to_absolute
- normalize_ocr/merge_ocr_lines（y_tol=16 行合并）
- last_quality 帧校验（PrintWindow 0.95 / mss 0.6 来源可信度）

## 可疑点（阶段二验证）

1. **CircuitBreaker `_tick_half_open` 只在 `__call__` 推进**——`allow()` 路径（若 VLM 调用用 allow + record_* 组合）可能永不进入 HALF_OPEN；需查 VLM 调用实际路径
2. EmergencyMonitor.stop() 只 set 不 join——daemon 线程，可接受；但 run() 中 `self._paused` 时 continue 跳过光标基准更新——resume 会重置，OK
3. FailureMemory.query 全文件读（无索引）——文件大时慢，但失败记录量小，可接受
4. ActionGuard.check 中 `_evidence_age` 返回 None（无证据）时 expired=False——无证据的已验证意图靠置信门槛；OK
5. guards/policy.py 注释说 interact 若按 30 上限会被未验证风险全部拦截——当前实现 interact 不在危险名单，走 MAX_SAFE_RISK(60)——保持
6. vision_gate.evaluate 需要细读打分逻辑（阶段二）
