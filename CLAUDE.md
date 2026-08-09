# WorldExecutor 项目记忆

## 项目
**WorldExecutor** — 崩坏：星穹铁道宝箱收集自动化助手（Windows/Python 3.11/PySide6）。
半自动：模板匹配定位 → SendInput 点击开箱；攻略视频 → VLM 识别 → 点位入库。

## 术语表
| 术语 | 含义 |
|------|------|
| M1-A | 真机闭环：截图→模板匹配→点击→verify 消失（已达成） |
| G3 门槛 | real 任务前 health 能力检查（window/capture/ocr/vlm/foreground/admin/input L0-L2） |
| L0/L1/L2 | 光标注入 / SendInput 注入 / 游戏响应探测（L2 会按 ESC——仅 gate 开启） |
| STEP_TYPES | 执行器白名单 {move, visual_guided_move, interact, verify} |
| 知识包 | knowledge/source/black_tower_test（31 目标：chest_A + 30 真点位） |
| pkg_key | 完成状态持久化域（知识目录 sha256——切地图自动隔离） |
| HUD | 游戏窗口左下角日志层（F10 紧急停止 + 点击穿透） |
| F10 | 全局紧急停止热键（keyboard 库——非 RegisterHotKey） |
| watchdog | SessionWatchdog 120s 事件静默 → deadlock 中断 |
| emergency | EmergencyMonitor 光标/前台/Esc 检测 → 人工介入暂停 |

## 关键架构
- 分层：app（入口）→ gui（PySide6）→ runtime（orchestrator/executor/输入）→ ingest（离线管线）→ knowledge（数据）
- 事件：EventBus 同步广播（订阅者异常隔离、弱引用、5000 环、jsonl 20MB 轮转）
- 输入链：March7thInputBackend → Win32Backend（SendInput/c_size_t 结构）
- 模板匹配：cv2 多尺度 21 级 + 1280 宽降采样（1.16s）+ manifest sha256 校验

## 历史决策（重要）
- 提权用 bat 里 PowerShell RunAs（ShellExecuteW runas 本机静默失败）
- pythonw 无控制台 + stdout None 重定向
- 模板阈值默认 0.60（实测 0.72-0.81）
- 风险等级四级 low/medium/high/critical（guard 动态推导）
- 完成状态持久化：mission_state:{pkg_key} 单 key 原子（QSettings）
- 连通性检查：有向 portal 图、仅图中节点

## 踩过的坑（勿重蹈）
- ctypes dwExtraInfo 必须 c_size_t（c_ulong 64 位结构错误 → SendInput 拒收）
- bat 必须 ASCII+CRLF（UTF-8 中文注释破坏 cmd 解析）
- argv 拼接必须引号（含空格路径截断）
- `all(空dict)` 恒 True → 空目标误报 all_done
- make_event 事件类型必须注册（mission_summary 漏注册 → real 任务必 crashed）
- qfluentwidgets ComboBox 无 setEditable（用原生 QComboBox）
- 函数内 import 使名字局部化（UnboundLocalError）
- hash() 跨进程不稳定（seed 用 sha256）
