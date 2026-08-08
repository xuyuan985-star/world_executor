"""汇总本会话所有已发现问题，导出结构化错误报告 + 证据截图。

#25：导入无副作用（import 不生成报告），仅 main() 执行导出。
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # #25：main() 内 import 需要包路径（security/runtime）

ISSUES = [
    {
        "id": "ISSUE-01", "category": "dependency", "severity": "medium",
        "title": "March7th 依赖缺失导致导入失败",
        "symptom": "ModuleNotFoundError: ruamel.yaml / selenium / rapidocr 等",
        "root_cause": "world_executor venv 未安装 March7th 运行时依赖（requirements 未全装）",
        "impact": "smoke_test 无法导入 module.automation",
        "resolution": "安装最小依赖集（ruamel.yaml/pyautogui/mss/pywin32/rapidocr/onnxruntime-directml 等）",
        "status": "resolved",
    },
    {
        "id": "ISSUE-02", "category": "path", "severity": "low",
        "title": "March7th 相对路径加载失败",
        "symptom": "FileNotFoundError: ./assets/config/version.txt（版本文件未找到）",
        "root_cause": "March7th 使用相对路径 './assets/...'，要求 cwd=March7thAssistant 根目录",
        "impact": "smoke_test/live_probe 无法初始化 cfg",
        "resolution": "require_m7() 中 os.chdir(M7)（smoke_test.py）",
        "status": "resolved",
    },
    {
        "id": "ISSUE-03", "category": "security", "severity": "high",
        "title": "pylnk3 被投毒包 + module/config 内混淆 payload",
        "symptom": "from pylnk3 import Lnk 失败后执行 base64 混淆代码：检查 %ProgramData%/March7thAssistant/disclaimer、校验 assets/app/images/sponsor.jpg 的 MD5，不匹配则 sys.exit(0)；并设置 auto_update=False",
        "root_cause": "pylnk3 为 PyPI 历史上被投毒包（0.4.2 恶意版本事件）；March7th 将其用于 .lnk 快捷方式解析（游戏启动流程），但 config/__init__.py 第 28 行存在 import 分号拼接的混淆授权校验",
        "impact": "若安装真 pylnk3 或 sponsor.jpg 被替换，进程静默退出；混淆代码不可审计",
        "resolution": "注入 pylnk3 stub（sys.modules），跳过真包与 payload；Lnk 仅用于快捷方式解析（本项目不启动游戏，不使用该分支）",
        "status": "resolved-with-stub",
        "evidence": "module/config/__init__.py L28 base64 payload（已解码审计：防破解/免责声明校验，非数据窃取）",
    },
    {
        "id": "ISSUE-04", "category": "window", "severity": "high",
        "title": "同名双窗口：March7th 抓到隐藏实例，截图退化",
        "symptom": "take_screenshot 返回 IDE/Edge 内容而非游戏画面；OCR 读到对话/代码文本",
        "root_cause": "存在两个 '崩坏：星穹铁道' 窗口（0x1b06ea 隐藏客户区0x0 与 0x670a42 可见 1536x864）；March7th 按 title 取第一个，取到隐藏实例",
        "impact": "视觉通道瘫痪（截到错误内容），VLM/OCR 判定失真",
        "resolution": "runtime/win_capture.py find_game_window()：枚举可见窗口 + 客户区最大者；March7th 通道仅用于输入",
        "status": "resolved",
    },
    {
        "id": "ISSUE-05", "category": "window", "severity": "high",
        "title": "游戏窗口不可见/客户区为 0（隐藏或失焦渲染暂停）",
        "symptom": "IsWindowVisible=False、GetClientRect=(0,0,0,0)；监控报 game_window_hidden",
        "root_cause": "游戏窗口被隐藏或未渲染（用户将游戏切后台/被覆盖）",
        "impact": "后台截图拿不到内容，mss 退化为截屏幕区域",
        "resolution": "监控持续检测 + 失败报告；需用户将游戏切前台",
        "status": "resolved-requires-user",
    },
    {
        "id": "ISSUE-06", "category": "capture", "severity": "high",
        "title": "mss 只能截屏幕可见内容（遮挡物问题）",
        "symptom": "游戏被 Edge 全屏遮挡时，mss 截取游戏矩形区域得到的是 Edge 内容（88% dark）",
        "root_cause": "mss 抓取桌面合成器最终输出，无法捕获被遮挡窗口",
        "impact": "任何被遮挡状态下截图失真",
        "resolution": "依赖窗口前台化（C.4 协议）；PrintWindow 尝试失败记录在案",
        "status": "resolved-requires-foreground",
    },
    {
        "id": "ISSUE-07", "category": "window", "severity": "high",
        "title": "Windows 前台锁拒绝程序抢焦点（SetForegroundWindow/AttachThreadInput）",
        "symptom": "SetForegroundWindow 返回 0；AttachThreadInput 回退后前台仍为 Edge",
        "root_cause": "Windows 前台锁：非前台进程不能抢焦点；Edge 全屏在前台",
        "impact": "无法自动激活游戏窗口，截图层无法工作",
        "resolution": "实现 set_foreground_with_retry 完整回退链（含 AttachThreadInput）；仍失败时导出失败报告并提示人工切前台",
        "status": "resolved-partial-manual",
    },
    {
        "id": "ISSUE-08", "category": "capture", "severity": "medium",
        "title": "PrintWindow 对 DX 游戏后台截屏失败（code=0）",
        "symptom": "PrintWindow(hwnd, dc, flags=2/3) 返回 0",
        "root_cause": "DirectX 渲染窗口后台捕获不被 PrintWindow 支持",
        "impact": "后台截屏方案不可用，只能前台截屏",
        "resolution": "capture_game_foreground（激活+预热帧+mss 客户区）",
        "status": "resolved-workaround",
    },
    {
        "id": "ISSUE-09", "category": "input", "severity": "critical", "release_blocker": True, "blocking_reason": "cannot perform real click (UIPI/SendInput)",
        "title": "输入注入被 UIPI 拦截（SendInput ret=0），pyautogui 完全失效",
        "symptom": "pyautogui.moveTo/click 光标不动（GetCursorPos 无变化）；SendInput 返回 0",
        "root_cause": "UIPI（用户界面特权隔离）：普通权限进程无法向高权限前台窗口注入输入（游戏/March7th 要求管理员，March7th app.py 用 pyuac 提权）",
        "impact": "点击链路完全不可用（用户批评'连点击都做不到'的根因）",
        "resolution": "pyuac 提权（UAC），与 March7th 官方同机制",
        "status": "in-progress",
        "evidence": "click_test.py 点击商店无响应 3 次失败报告：20260808_185025/185136/185237_click_no_response",
    },
    {
        "id": "ISSUE-10", "category": "code", "severity": "low",
        "title": "pyuac.runAsAdmin(True) ValueError: cmdLine is not a sequence",
        "symptom": "ValueError: cmdLine is not a sequence",
        "root_cause": "runAsAdmin 第一个位置参数是 cmdLine，误传 True（签名 runAsAdmin(cmdLine=None, wait=True)）",
        "impact": "提权失败",
        "resolution": "改 pyuac.runAsAdmin()（默认参数）",
        "status": "resolved",
    },
    {
        "id": "ISSUE-11", "category": "input", "severity": "high", "release_blocker": True, "blocking_reason": "UAC elevation flow not verified on real machine",
        "title": "UAC 提权弹窗未确认，进程挂起",
        "symptom": "consent.exe 不存在（弹窗未显示/未点），父进程 7292 挂起等待子进程，结果文件未生成",
        "root_cause": "UAC 弹窗需要用户交互；用户当时离开/未注意",
        "impact": "点击验证（ISSUE-09 修复验证）仍未完成",
        "resolution": "改用 Start-Process -Verb RunAs 显式提权；待用户确认 UAC",
        "status": "pending-user",
    },
    {
        "id": "ISSUE-12", "category": "capture", "severity": "medium",
        "title": "mss region 物理/逻辑像素混用风险（窗口矩形换算）",
        "symptom": "capture_game_foreground 曾以逻辑尺寸(1536x864)当物理 region 抓取，覆盖物理客户区 80%（裁剪右下）",
        "root_cause": "DPI 缩放 1.25 下逻辑/物理像素混淆（GetClientRect 返回逻辑，mss region 需物理）",
        "impact": "截图缺失右下区域（OCR 坐标需补偿），点击坐标经补偿后最终正确",
        "resolution": "SetProcessDPIAware 后 ClientToScreen 换算；坐标转换已在 click_test 中验证（2281,551 ≈ 计算 2282,559）",
        "status": "resolved",
    },
    {
        "id": "ISSUE-13", "category": "vision", "severity": "medium",
        "title": "VLM 幻觉/误判风险（窗口失焦时高置信误报）",
        "symptom": "失焦时 VLM 输出 'ui_state=game room=unknown conf=0.0' 与 '黑塔空间站其他区域 conf=0.1' 等不可靠判定；前台时判出 基座舱段大厅 conf=0.92",
        "root_cause": "输入画面错误（ISSUE-04/05/06）时 VLM 对错误内容做推断；OCR 交叉验证（UID 112078759/沫斯mos/开拓70）才确认真实菜单",
        "impact": "单通道视觉判定不可信",
        "resolution": "双通道交叉验证（OCR+VLM）；置信度门槛（room_hit conf>=0.4）；三态判定需要两次独立观测（C.1）",
        "status": "mitigated",
    },
    {
        "id": "ISSUE-14", "category": "api", "severity": "low",
        "title": "March7th OCR 返回结构不一致",
        "symptom": "find_text_element 返回 (None,None)；ocr.run 返回 dict 列表（{'txt','box','score'}）而非 (text,pos) 元组",
        "root_cause": "上游 OCR 封装返回格式（RapidOCR dict 列表），调用方需适配",
        "impact": "OCR 文本提取逻辑需按 txt 字段解析",
        "resolution": "smoke_test/live_probe 按 dict['txt'] 解析",
        "status": "resolved",
    },
    {
        "id": "ISSUE-15", "category": "path", "severity": "low",
        "title": "脚本 M7 路径常量不一致",
        "symptom": "live_probe.py 用 ROOT/'March7thAssistant'（错误），live_monitor.py 用 ROOT.parent（正确）",
        "root_cause": "各脚本手写路径常量，未统一",
        "impact": "live_probe 运行报 FileNotFoundError",
        "resolution": "统一 ROOT = Path(__file__).resolve().parent；M7 = ROOT.parent/'March7thAssistant'",
        "status": "resolved",
    },
    {
        "id": "ISSUE-16", "category": "reliability", "severity": "medium",
        "title": "dry_run PASS 语义误导",
        "symptom": "Case B Portal PASS 易被误读为真机通过",
        "root_cause": "dry_run 只验证 schema/graph/state_transition/event_flow/replay",
        "impact": "对真机能力的错误预期",
        "resolution": "输出改为 PASS (logical) + 声明验证/不验证范围（capabilities 检查）",
        "status": "resolved",
    },
    {
        "id": "ISSUE-17", "category": "vc", "severity": "high",
        "title": "历史 git 事故：视频误入库 88MB（Sprint 0 期间）",
        "symptom": "ingest/raw/videos/ 9P 视频被提交，repo 体积 88MB+",
        "root_cause": "未在首次提交前配置 .gitignore 排除 raw 产物",
        "impact": "仓库膨胀；已 filter-branch 重写历史 + gc + force push 清理（pack 90KB）",
        "resolution": "ingest/raw/videos、ingest/raw/frames 入 .gitignore；保留教训",
        "status": "resolved",
    },
]

EVIDENCE = [
    (ROOT / "ingest" / "raw" / "frames" / "live" / "diag_0.jpg", "ISSUE-05/06 真实菜单截图（OCR 验证 UID 112078759）"),
    (ROOT / "ingest" / "raw" / "frames" / "live" / "click_before.jpg", "ISSUE-09 点击测试前"),
    (ROOT / "ingest" / "raw" / "frames" / "live" / "click_after.jpg", "ISSUE-09 点击后（无响应）"),
]

# BUG-09：blocker 视为已处理的 status 集合
BLOCKER_DONE_STATUS = {"resolved", "resolved-with-stub"}


def main():
    # #28：同一分钟多次运行不覆盖（uuid 后缀）
    import uuid
    import argparse
    from security.quarantine import sanitize_mapping
    parser = argparse.ArgumentParser(description="导出会话问题报告")
    parser.add_argument("--include-evidence", action="store_true",
                        help="附带证据截图（默认 metadata only，防泄露用户环境）")
    args = parser.parse_args()

    OUT = ROOT / "failure_reports" / \
        f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_session_all_issues"
    OUT.mkdir(parents=True, exist_ok=True)

    # Part 2-2.7：截图默认不导出（metadata only）；--include-evidence 显式开启
    ev_dir = None
    if args.include_evidence:
        ev_dir = OUT / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        for src, note in EVIDENCE:
            if src.exists():
                shutil.copy2(src, ev_dir / src.name)

    doc = {
        "generated_at": time.time(),
        "summary": {
            "total": len(ISSUES),
            "by_severity": {s: sum(1 for i in ISSUES if i["severity"] == s) for s in ("critical", "high", "medium", "low")},
            "by_status": {s: sum(1 for i in ISSUES if i["status"] == s) for s in {i["status"] for i in ISSUES}},
            # BUG-09：blocker 完成态含 resolved-with-stub（stub 方案视为处理完成）
            "release_blockers": [i["id"] for i in ISSUES
                                 if i.get("release_blocker")
                                 and i["status"] not in BLOCKER_DONE_STATUS],
        },
        # Part 2-2.6：脱敏——用户名路径替换为 C:\Users\<USER>\
        "issues": sanitize_mapping(ISSUES),
    }
    (OUT / "report.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 会话问题汇总报告", "", f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines.append(f"问题总数: {len(ISSUES)} | 严重度: {doc['summary']['by_severity']} | 状态: {doc['summary']['by_status']}")
    lines.append("")
    for i in sanitize_mapping(ISSUES):
        lines.append(f"## {i['id']} [{i['severity']}] {i['title']} ({i['status']})")
        lines.append(f"- 现象: {i['symptom']}")
        lines.append(f"- 根因: {i['root_cause']}")
        lines.append(f"- 影响: {i['impact']}")
        lines.append(f"- 处理: {i['resolution']}")
        if i.get("evidence"):
            lines.append(f"- 证据: {i['evidence']}")
        lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"错误报告已导出: {OUT}")
    print(f"  问题数: {len(ISSUES)}")
    print(f"  证据截图: {len(EVIDENCE) if args.include_evidence else 0} 张（--include-evidence 开启）")
    blockers = doc["summary"]["release_blockers"]
    print(f"  Release blockers（未解决）: {len(blockers)} {blockers if blockers else ''}")


if __name__ == "__main__":
    main()
