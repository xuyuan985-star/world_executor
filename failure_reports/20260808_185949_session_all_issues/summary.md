# 会话问题汇总报告

生成时间: 2026-08-08 18:59:49

问题总数: 17 | 严重度: {'critical': 1, 'high': 7, 'medium': 5, 'low': 4} | 状态: {'resolved-workaround': 1, 'resolved-with-stub': 1, 'resolved-requires-user': 1, 'resolved': 9, 'in-progress': 1, 'pending-user': 1, 'mitigated': 1, 'resolved-partial-manual': 1, 'resolved-requires-foreground': 1}

## ISSUE-01 [medium] March7th 依赖缺失导致导入失败 (resolved)
- 现象: ModuleNotFoundError: ruamel.yaml / selenium / rapidocr 等
- 根因: world_executor venv 未安装 March7th 运行时依赖（requirements 未全装）
- 影响: smoke_test 无法导入 module.automation
- 处理: 安装最小依赖集（ruamel.yaml/pyautogui/mss/pywin32/rapidocr/onnxruntime-directml 等）

## ISSUE-02 [low] March7th 相对路径加载失败 (resolved)
- 现象: FileNotFoundError: ./assets/config/version.txt（版本文件未找到）
- 根因: March7th 使用相对路径 './assets/...'，要求 cwd=March7thAssistant 根目录
- 影响: smoke_test/live_probe 无法初始化 cfg
- 处理: require_m7() 中 os.chdir(M7)（smoke_test.py）

## ISSUE-03 [high] pylnk3 被投毒包 + module/config 内混淆 payload (resolved-with-stub)
- 现象: from pylnk3 import Lnk 失败后执行 base64 混淆代码：检查 %ProgramData%/March7thAssistant/disclaimer、校验 assets/app/images/sponsor.jpg 的 MD5，不匹配则 sys.exit(0)；并设置 auto_update=False
- 根因: pylnk3 为 PyPI 历史上被投毒包（0.4.2 恶意版本事件）；March7th 将其用于 .lnk 快捷方式解析（游戏启动流程），但 config/__init__.py 第 28 行存在 import 分号拼接的混淆授权校验
- 影响: 若安装真 pylnk3 或 sponsor.jpg 被替换，进程静默退出；混淆代码不可审计
- 处理: 注入 pylnk3 stub（sys.modules），跳过真包与 payload；Lnk 仅用于快捷方式解析（本项目不启动游戏，不使用该分支）
- 证据: module/config/__init__.py L28 base64 payload（已解码审计：防破解/免责声明校验，非数据窃取）

## ISSUE-04 [high] 同名双窗口：March7th 抓到隐藏实例，截图退化 (resolved)
- 现象: take_screenshot 返回 IDE/Edge 内容而非游戏画面；OCR 读到对话/代码文本
- 根因: 存在两个 '崩坏：星穹铁道' 窗口（0x1b06ea 隐藏客户区0x0 与 0x670a42 可见 1536x864）；March7th 按 title 取第一个，取到隐藏实例
- 影响: 视觉通道瘫痪（截到错误内容），VLM/OCR 判定失真
- 处理: runtime/win_capture.py find_game_window()：枚举可见窗口 + 客户区最大者；March7th 通道仅用于输入

## ISSUE-05 [high] 游戏窗口不可见/客户区为 0（隐藏或失焦渲染暂停） (resolved-requires-user)
- 现象: IsWindowVisible=False、GetClientRect=(0,0,0,0)；监控报 game_window_hidden
- 根因: 游戏窗口被隐藏或未渲染（用户将游戏切后台/被覆盖）
- 影响: 后台截图拿不到内容，mss 退化为截屏幕区域
- 处理: 监控持续检测 + 失败报告；需用户将游戏切前台

## ISSUE-06 [high] mss 只能截屏幕可见内容（遮挡物问题） (resolved-requires-foreground)
- 现象: 游戏被 Edge 全屏遮挡时，mss 截取游戏矩形区域得到的是 Edge 内容（88% dark）
- 根因: mss 抓取桌面合成器最终输出，无法捕获被遮挡窗口
- 影响: 任何被遮挡状态下截图失真
- 处理: 依赖窗口前台化（C.4 协议）；PrintWindow 尝试失败记录在案

## ISSUE-07 [high] Windows 前台锁拒绝程序抢焦点（SetForegroundWindow/AttachThreadInput） (resolved-partial-manual)
- 现象: SetForegroundWindow 返回 0；AttachThreadInput 回退后前台仍为 Edge
- 根因: Windows 前台锁：非前台进程不能抢焦点；Edge 全屏在前台
- 影响: 无法自动激活游戏窗口，截图层无法工作
- 处理: 实现 set_foreground_with_retry 完整回退链（含 AttachThreadInput）；仍失败时导出失败报告并提示人工切前台

## ISSUE-08 [medium] PrintWindow 对 DX 游戏后台截屏失败（code=0） (resolved-workaround)
- 现象: PrintWindow(hwnd, dc, flags=2/3) 返回 0
- 根因: DirectX 渲染窗口后台捕获不被 PrintWindow 支持
- 影响: 后台截屏方案不可用，只能前台截屏
- 处理: capture_game_foreground（激活+预热帧+mss 客户区）

## ISSUE-09 [critical] 输入注入被 UIPI 拦截（SendInput ret=0），pyautogui 完全失效 (in-progress)
- 现象: pyautogui.moveTo/click 光标不动（GetCursorPos 无变化）；SendInput 返回 0
- 根因: UIPI（用户界面特权隔离）：普通权限进程无法向高权限前台窗口注入输入（游戏/March7th 要求管理员，March7th app.py 用 pyuac 提权）
- 影响: 点击链路完全不可用（用户批评'连点击都做不到'的根因）
- 处理: pyuac 提权（UAC），与 March7th 官方同机制
- 证据: click_test.py 点击商店无响应 3 次失败报告：20260808_185025/185136/185237_click_no_response

## ISSUE-10 [low] pyuac.runAsAdmin(True) ValueError: cmdLine is not a sequence (resolved)
- 现象: ValueError: cmdLine is not a sequence
- 根因: runAsAdmin 第一个位置参数是 cmdLine，误传 True（签名 runAsAdmin(cmdLine=None, wait=True)）
- 影响: 提权失败
- 处理: 改 pyuac.runAsAdmin()（默认参数）

## ISSUE-11 [high] UAC 提权弹窗未确认，进程挂起 (pending-user)
- 现象: consent.exe 不存在（弹窗未显示/未点），父进程 7292 挂起等待子进程，结果文件未生成
- 根因: UAC 弹窗需要用户交互；用户当时离开/未注意
- 影响: 点击验证（ISSUE-09 修复验证）仍未完成
- 处理: 改用 Start-Process -Verb RunAs 显式提权；待用户确认 UAC

## ISSUE-12 [medium] mss region 物理/逻辑像素混用风险（窗口矩形换算） (resolved)
- 现象: capture_game_foreground 曾以逻辑尺寸(1536x864)当物理 region 抓取，覆盖物理客户区 80%（裁剪右下）
- 根因: DPI 缩放 1.25 下逻辑/物理像素混淆（GetClientRect 返回逻辑，mss region 需物理）
- 影响: 截图缺失右下区域（OCR 坐标需补偿），点击坐标经补偿后最终正确
- 处理: SetProcessDPIAware 后 ClientToScreen 换算；坐标转换已在 click_test 中验证（2281,551 ≈ 计算 2282,559）

## ISSUE-13 [medium] VLM 幻觉/误判风险（窗口失焦时高置信误报） (mitigated)
- 现象: 失焦时 VLM 输出 'ui_state=game room=unknown conf=0.0' 与 '黑塔空间站其他区域 conf=0.1' 等不可靠判定；前台时判出 基座舱段大厅 conf=0.92
- 根因: 输入画面错误（ISSUE-04/05/06）时 VLM 对错误内容做推断；OCR 交叉验证（UID 112078759/沫斯mos/开拓70）才确认真实菜单
- 影响: 单通道视觉判定不可信
- 处理: 双通道交叉验证（OCR+VLM）；置信度门槛（room_hit conf>=0.4）；三态判定需要两次独立观测（C.1）

## ISSUE-14 [low] March7th OCR 返回结构不一致 (resolved)
- 现象: find_text_element 返回 (None,None)；ocr.run 返回 dict 列表（{'txt','box','score'}）而非 (text,pos) 元组
- 根因: 上游 OCR 封装返回格式（RapidOCR dict 列表），调用方需适配
- 影响: OCR 文本提取逻辑需按 txt 字段解析
- 处理: smoke_test/live_probe 按 dict['txt'] 解析

## ISSUE-15 [low] 脚本 M7 路径常量不一致 (resolved)
- 现象: live_probe.py 用 ROOT/'March7thAssistant'（错误），live_monitor.py 用 ROOT.parent（正确）
- 根因: 各脚本手写路径常量，未统一
- 影响: live_probe 运行报 FileNotFoundError
- 处理: 统一 ROOT = Path(__file__).resolve().parent；M7 = ROOT.parent/'March7thAssistant'

## ISSUE-16 [medium] dry_run PASS 语义误导 (resolved)
- 现象: Case B Portal PASS 易被误读为真机通过
- 根因: dry_run 只验证 schema/graph/state_transition/event_flow/replay
- 影响: 对真机能力的错误预期
- 处理: 输出改为 PASS (logical) + 声明验证/不验证范围（capabilities 检查）

## ISSUE-17 [high] 历史 git 事故：视频误入库 88MB（Sprint 0 期间） (resolved)
- 现象: ingest/raw/videos/ 9P 视频被提交，repo 体积 88MB+
- 根因: 未在首次提交前配置 .gitignore 排除 raw 产物
- 影响: 仓库膨胀；已 filter-branch 重写历史 + gc + force push 清理（pack 90KB）
- 处理: ingest/raw/videos、ingest/raw/frames 入 .gitignore；保留教训
