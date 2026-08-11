# WorldExecutor 项目记忆

## 项目
**WorldExecutor** — 崩坏：星穹铁道宝箱收集自动化助手（Windows/Python 3.14/PySide6）。
半自动：模板匹配定位 → SendInput 点击开箱；攻略视频 → VLM 识别 → 点位入库。

## 架构（0.6.0 回滚：任务中心 = QProcess 子进程 + 项目内 m7/）
- **宝箱收集链全自研**（运行时零依赖外部 March7thAssistant）：
  - 截图：`runtime/win_capture`（PrintWindow 后台 → 前台 mss 兜底）
  - OCR：`runtime/ocr_engine`（rapidocr 直连——rapidocr 3.8 返回 RapidOCROutput，
    用 `.txts/.boxes`，勿用旧 tuple 解包）
  - 模板匹配：`runtime/input/template_backend`（cv2 多尺度）
  - 输入：`runtime/input/win32_backend`（SendInput）
  - 地图传送资产：`assets/fhoe/`
- **任务中心 = QProcess 子进程**（0.6.0 回滚——0.5.0 进程内 QThread 集成
  反复 0xC0000409 崩溃，结构性根因：m7 是独立进程程序，塞进 GUI 进程
  违反其架构假设）：
  - QProcess 启动 `m7_venv\Scripts\python.exe -u m7_launcher.py <task>`
  - m7_launcher：pylnk3 stub 注入 → runpy 跑 **项目内 `m7/main.py`**
  - m7 在独立进程：cwd/单例/配置/Qt 全局零冲突；崩了只是子进程崩；
    停止 = kill 即停；日志 = 管道 readyRead 实时
  - m7 源码：项目内 `m7/`（主路径，gitignore 不入库，setup_m7 克隆官方仓库）；
    旧外部 `March7thAssistant` 仅作更新镜像/兜底
- `runtime/drivers/march7th/` 仅剩薄接口名（类名不变，实现全自研）。

## 环境（2026-08-11 统一）
- **唯一环境 = `m7_venv`（Python 3.12+，当前 3.14.2）**——GUI 与 m7 任务中心同环境同进程。
  旧 `.venv`（3.11）已删除（3.11 无法进程内 `import main`——m7 用 PEP 701 f-string）。
- 所有命令用 `m7_venv\Scripts\python.exe`（或 pythonw）。系统 `python` 缺 PySide6 勿用。
- 启动：双击 bat 或 `m7_venv\Scripts\pythonw.exe -m app`。
- bat 自检：m7_venv 缺失或 <3.12 → 自动重建。
- **坑：Python 3.14 生态**——requirements 锁的旧版（numpy 2.2.6/opencv 4.11/pillow 10.4）
  在 3.14 无预编译 wheel → pip 走源码编译必失败。必须用 requirements.txt 当前的 3.14 兼容版
  （numpy 2.5.2/opencv 5.0/pillow 12.3 等）。升级版本前先确认有 cp314 wheel。
- **坑：验证依赖要用真实 `import` 而非 `importlib.metadata`**（dist-info 残留会误判"已装"——
  m7_venv 曾因 setup_m7 装依赖失败成空壳却 metadata 显示齐全）。
- **坑：m7_venv 必须装两类依赖**——world_executor `requirements.txt` + m7 的
  `March7thAssistant/requirements.txt`（排除 pylnk3，见 `m7_requirements_nopylnk.txt`）。
  只装前者 → March7thVision 构造失败（缺 colorama 等）→ 指挥台实时观测/观察中心截图瘫痪
  （异常被 except 吞成占位）。setup_m7.py 已含过滤安装逻辑。

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
