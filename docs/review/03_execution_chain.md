# R3 执行链审查（2026-08-12）

## 执行流水线

```
run_mission(target_ids, emergency=True)        [会话级]
 ├─ stop_check 前置检查（F10 启动期按下 → 直接返回）
 ├─ start_emergency() + start_watchdog()
 ├─ _replay_only 判定 → _ensure_foreground()（纯回放也拉游戏置顶）
 ├─ 非纯回放 → _ensure_game_ready()（界面归一化，最多 6 轮）
 ├─ 目标去重（dict.fromkeys 保持顺序）
 └─ for tid: run_target(tid)                    [单目标级]
     ├─ stop/emergency/stall 前置检查
     ├─ 遇怪策略 _handle_battle_if_needed（auto=自动战斗 v / kill=战技 e）
     ├─ 窗口状态 _window_lost（消失/过小/失焦——失焦激活一次重试）
     ├─ for step: _run_step → 失败重试（retryable + 指数退避 ≤1.5s）
     └─ finally: stop_emergency()
```

## 状态机（state_machine.py）

- 11 状态 × 15 事件，TRANSITIONS 表驱动；非法迁移 ValueError（fail-closed）
- INIT --START--> CHECK_WORLD_STATE --ROOM_MATCH--> NAVIGATING --TARGET_VISIBLE--> VERIFYING --TARGET_VERIFIED--> INTERACTING --INTERACT_OK--> DONE
- 失败路径：EVENT_INTERRUPTED → EVENT_INTERRUPT --RECOVER_OK--> NAVIGATING；ROOM_MISMATCH → RECOVERING；ABORT_REQUEST → ABORT（RECOVERING 补了 ABORT 边——审查 P1-4）
- 每次迁移 db.record_state_observation

## 步骤类型白名单（STEP_TYPES）

move / visual_guided_move / interact / verify / portal / trajectory —— 未知类型 F3 fail-fast

## 失败分类体系

F1（执行异常）F2（验证/坐标/超时）F3（知识/权限/窗口）F4（视觉不可信）F5（动作闸门）F6（权限）；ErrorCode 枚举优先，字符串子串兜底；PERMANENT_CODES 强制 retryable=False

## 关键机制

1. **SessionWatchdog**：120s 事件静默 → deadlock_detected + tripped；订阅存句柄 stop 时取消（防泄漏）；daemon 线程
2. **EmergencyMonitor**：人工介入 → is_paused() 暂停执行；执行点击前 suspend_mouse（自伤防护）
3. **重试策略**：retryable 才重试（模板缺/低置信/非幂等不重试）；指数退避 1s→2s→4s 上限 1.5s；MAX_TARGET_ATTEMPTS=3 硬上限
4. **轨迹回放步骤**：trajectory 前插（chests.json 的 trajectory 字段）；回放期 suspend EmergencyMonitor 鼠标检测；15s 节流心跳防 watchdog 误判
5. **界面归一化**：OCR 关键词四类——弹窗（稍后再看/前情提要/跳过剧情）点按钮、异常（重连）点确定等 20s、战斗/菜单 ESC；6 轮超时 RuntimeError（crashed 诚实失败）
6. **verify_signal**：基线探测 2s（防视频帧模板恒不中→vanished 恒真的假阳性）；vanished/present；delay 0.2→1.5 指数退避；abort_check 每 tick
7. **模板兜底链**：模板未命中 → 知识包实体归一化坐标 → _click_with_diff_verify（点击前后像素差分 + 8 方向 nudge 微调）
8. **VLM bbox**：OBS_MAX_AGE=1.5s + OBS_MIN_CONFIDENCE=0.6 + 越界保护（≤20000）+ 帧校验钩子（默认放行）
9. **map_transfer**（Fhoe 传送链）：M 开图 → Fhoe 模板序列点击 → load_wait + 画面稳定检测
10. **ActionGuard**：执行前置闸门（strict=False 宽松；F4/F5 分离 + evidence_store TTL/容量管理）

## 观察到的可疑点（阶段二验证）

1. **`_current_target` 从未赋值**——trajectory 进度事件 context["target"] 恒 None（audit 信息缺失，不影响执行）
2. `_step_portal` 中 portal_transition 返回 False 与 ExecutionResult 混用——调用方 _run_step 只认 result.success，False 会被当失败但无 error/category（`if not result.success` → result.error None → "step_failed" 兜底）——retryable 判断 OK 但错误分类模糊
3. `run_mission` 的 `_replay_only` 判定对无 workflow 且无轨迹文件的 target 返回 False——OK；但对"轨迹+其他步骤混合"的 workflow 返回 False 走完整界面归一化——混合场景会 15s 静默，可接受
4. `move_visual_guided` 的 reached_center 失败分类 F2_COORD retryable=True——orchestrator 会重试；VGM 不推进状态机（#41/#42 语义）
5. `_step_interact` 在 interact_template 成功后手动 on(TARGET_VISIBLE) + on(TARGET_VERIFIED)——两步迁移连发，中间无 VERIFYING 停留；但 _step_verify 又在 INTERACTING 态 INTERACT_OK——路径合理
