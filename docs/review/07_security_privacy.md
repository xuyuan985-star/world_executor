# R7 安全与隐私层审查（2026-08-12）

## 健康检查（runtime/health.py 211 行）

- 8+2 通道：window/capture/ocr/vlm/foreground/admin/input(L0/L1/L2)/ffmpeg/disk
- **L0 光标回读、L2 ESC 注入探测默认关闭（input_probe=False）**——GUI 轮询健康检查必须零副作用（每 5s 抢鼠标/按 ESC 的历史教训）
- L1 SendInput 无副作用注入（dx=dy=0 的 MOUSEEVENTF_MOVE）
- 输入汇总：未测（None）不算失败
- all_ok 排除 input_l2（L2 未测不算失败）

## G3 门槛（RuntimeAPI._gate_check）

- **critical 硬拦**：window/capture/ocr/vlm（缺了真没法跑）
- **warning 不拦**：foreground/admin/input L0-L2（0.6.0 调整——非管理员对同权限游戏 SendInput 有效；拉置顶失败执行中会重试；硬拦导致挫败感）
- spec.requires 可追加硬拦键
- gate 路径 input_probe=True + auto_activate=True（真机才按 ESC/抢前台）
- 失败 → run_finished(gate_blocked) + mode（READY/OBSERVE_ONLY/BLOCKED via detect_capability）

## 状态机（runtime/api/commands.py + state.py）

- MissionState 枚举统一（idle/initializing/running/paused/success/failed/crashed/stopped/gate_blocked/invalid）
- RuntimeAPI：VALID_STATES 白名单 + _set_state 校验；stop 保留 _thread 引用（防重入靠 is_alive）
- runner 线程：validate → 启动游戏（窗口缺失）→ gate → run_mission → mission_summary → run_finished
- **stopped 语义保留**（F10 停止 ≠ 崩溃——不覆盖成 done/crashed）
- 空目标 → no_targets（all(空dict) 恒 True 坑的防御）
- 纯轨迹回放跳过 G3 门槛（0.6.0：秒开）

## 隐私/脱敏面

1. **quarantine.sanitize_text**：`C:\Users\<用户名>` → `<USER>`（str.replace 非 re.sub——反斜杠序列坑）；sanitize_mapping 递归
2. **FailureReporter**：report.json/environment.json 均经 sanitize_mapping；环境快照含 git commit/DPI/OS/Python
3. **config.settings.install_log_redaction**：日志脱敏（API key/cookie）
4. **EventBus jsonl**：events 持久化未脱敏——context 可能含路径（阶段二检查泄露面）
5. **FailureMemory.jsonl**：failure/context 未脱敏——含 target 等，无路径字段（需确认）
6. git 泄露面：.gitignore 是否覆盖 logs/reports/*.json/memory/failures.jsonl（阶段二核对）

## 其他

- win_capture：PrintWindow 后台截图 → mss 前台兜底；set_foreground_with_retry（3 次）
- game_launcher：m7 config.yaml 读 game_path → cmd start → 等窗口 360s → 点"点击进入"
- ocr_engine：rapidocr 直连（.txts/.boxes 新 API）
- March7thInputBackend：薄适配（自研 win32 后端）
- CapabilityRegistry：capabilities.yaml 静态能力表 + 深拷贝防污染 + 类型校验

## 可疑点（阶段二验证）

1. health.all_ok 排除 input_l2——若 L2 真测且失败（gate 路径），all_ok 仍 True？`all(v for k,v in ... if k not in ("input_l2",))` —— gate 路径 L2=False 时 all_ok 可能 True，但 _gate_check 不依赖 all_ok（用 fails/warns 列表）——OK
2. `ensure_game_launched` 360s 等待在 runner 线程（daemon）——GUI 不卡；但启动失败只发 state_changed 不拦（后续 gate window=False 拦）——OK
3. EventBus jsonl 未脱敏——路径信息落盘（隐私面，阶段二核对）
4. FailureMemory 未脱敏——同上
5. commands.py `self._pending_requires` 在 gate 后未清——下次 start 会残留？`start_mission` 每次都重设 `self._pending_requires = spec.requires`——OK
6. RuntimeAPI._thread 防重入：`is_alive()` 判断——stop 后线程仍在收尾（is_alive True）→ 再 start 抛 RuntimeError；合理
