# R2 输入链审查（2026-08-12）

## 分层（runtime/input/）

| 文件 | 角色 |
|---|---|
| base.py | InputResult + InputBackendProtocol（契约防接口漂移）+ InputBackend 基类 |
| win32_backend.py | 真实后端：SendInput 点击 / SetCursorPos 移动 / keybd_event 按键（174 行） |
| template_backend.py | 自研模板匹配：cv2 多尺度 + mask 匹配 + 降采样 1280 宽 + sha256 清单校验（218 行） |
| recorder.py | 轨迹录制：pynput 钩子，WASD/视角/点击/长按，白名单 + 诊断（334 行） |
| replayer.py | 轨迹回放：mouse_event 真相对视角 + 合并步长 + 分段等待 + 灵敏度换算（215 行） |
| replay.py | ReplayInput：测试确定性输入（预置结果队列） |
| observe.py | ObserveOnlyInput：输入只读降级（UIPI 无权限时系统不崩） |
| mock_backend.py | 简单 mock |

## Win32Backend 关键点

- `click/click_down/click_up/click_hold`：INPUT 结构 dwExtraInfo 必须 `c_size_t`（c_ulong 64 位结构错误 → SendInput 拒收——踩过的坑）
- `move`：SetCursorPos 绝对定位（普通点击用；**视角不用这个**——见 replayer）
- `press_key`：keybd_event + pressed_keys 登记 + finally 异常释放（Bug 385/386）
- `release_key`：只发 keyup 不等（#42）
- `_vk`：显式键名映射（ord 首字母坑：shift→S）
- UIPI 拦截 → `success=False, error="uipi_block"`（不是异常）

## 视角回放核心机制（0.6.0 实锤修复）

**链路**：pynput Controller.move = 读当前位置+位移 → SetCursorPos（假相对，绝对跳变）→ 指针锁定游戏不认 → 视角不动。游戏指针锁定模式只认 `mouse_event(MOUSEEVENTF_MOVE)` 增量事件（Fhoe-Rail 同款，mouse_event.py:237-262）。

- `_replay_view(dx, dy)`：`mouse_event(0x0001, ix, iy, 0, 0)`——无 ABSOLUTE 标志的真相对移动
- 小数像素累积 `_view_remain`：int() 截断会让慢速视角（单帧 <1px）归零——累积余量
- 录制 3px 粒度（`_view_acc` 累积阈值）→ 回放合并 ≥8px 步长 + 0.3s 间隔判定（防游戏输入死区吞小位移）
- 灵敏度换算：录制/回放灵敏度不同 → 视角像素位移 ×(gs_rec/gs_play)，视角角度一致
- 分辨率归一化：点击存客户区归一化 (nx,ny)，视角存归一化位移，回放按当前客户区换算；分辨率不一致 log 提示近似
- 分段等待：长 sleep 分 0.1s 段检查 abort + 1s 心跳 progress（F10 急停可中断）

## 录制（recorder.py）

- pynput keyboard+mouse 双钩子；3 秒启动缓冲（切窗口时间）
- 按键白名单：w/a/s/d/e/f/r/v/x/space/esc/shift/ctrl/1-4
- 键盘诊断三件套：_diag_keys（钩子收到的全部）/ _diag_filtered（白名单外）/ _diag_releases（孤儿 release）——区分"钩子死"vs"白名单过滤"
- 视角小位移累积 3px 阈值（连续慢移不漏录）
- 点击记录按下/释放（duration≥0.05s 支持长按回放）；客户区原点换算归一化
- stop()：listener.stop + join(1s) 等钩子线程退出（防停止后事件追加）；finally 注销全局 _active_recorder
- save()：默认命名 自定义-N；payload 含 version/recorded_at/client_w/h/game_sensitivity/events/count
- 全局 `_active_recorder` 注册（GUI closeEvent 停录制防钩子残留）

## 模板匹配（template_backend.py）

- SCALES 21 级（0.4-2.5 步长 0.1，43 级→21 级性能优化）
- 截图 mss → 降采样 1280 宽工作空间（1440p 全屏 43 级实测 15.7s → 现在 <1.5s）
- 模板缓存：mtime 校验（文件变更自动重读）；np.fromfile+imdecode（cv2.imread 中文路径坑）
- 透明 PNG → alpha mask + TM_CCORR_NORMED（m7 的 TM_SQDIFF 分数语义反转弃用）
- 无 mask：TM_CCOEFF_NORMED；多尺度取全局最高分（隐式 NMS）
- scale_range（workflow 声明）优先 + 40% 外扩；未达阈值回退全 SCALES
- templates_manifest.json sha256 校验（文件被换内容防 false positive）
- 阈值默认 0.60（实测 0.72-0.81）
- 中心坐标 = 命中尺度缩放尺寸（审查 P0 修过）

## 观察到的可疑点（阶段二验证）

1. `click_template` 重试耗尽后 `return None`——调用方解包 None 的行为需确认（orchestrator 路径）
2. recorder `_on_press` 重复按下（key 在 _key_down 中）直接 return 但 `_diag_keys` 仍记录——诊断计数与事件不一致（无碍功能）
3. recorder 无右键/中键过滤？`_on_click` 只处理 Button.left，其余静默——OK
4. `replay.py` 的 `available` 属性恒 True 未用？
5. replayer 对未知事件类型（既非 key/click/view_dx）静默跳过——OK（向后兼容）
