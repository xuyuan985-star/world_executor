# tools/calibration/click_test.py

```python
"""校准工具（G2 门槛）：验证 March7th 输入链路（提权 + OCR 定位 + 点击 + UI 响应）。

声明：
  · 仅用于验证 March7th 原语（提权/SendInput/后台截图/坐标换算），
    **不属于 runtime execution path**——禁止把本文件的坐标换算逻辑复制进 runtime。
  · v0.12.1 起执行层不接触坐标：runtime 只产 ActionIntent，
    由 March7th Driver（auto.click_element）内部完成模板匹配与绝对换算。
  · 本文件的 scale_factor 自算是校准场景特例（OCR box 来自原始截图），
    与执行器无关，仅此处允许。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
M7 = ROOT.parent / "March7thAssistant"
RESULT_FILE = ROOT / "click_test_result.txt"


def tee(msg):
    print(msg)
    with open(RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def ocr_lines(ocr_engine, img):
    # BUG-23：空图保护（np.asarray(None) → object 数组会让 RapidOCR 崩）
    if img is None:
        return []
    import numpy as np
    arr = np.asarray(img)
    r = ocr_engine.run(arr)
    out = []
    for t in r or []:
        if isinstance(t, dict) and t.get("txt"):
            out.append((t["txt"], t["box"]))
    return out


def box_center(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def main():
    from security.quarantine import install_pylnk3_stub, require_m7_path
    require_m7_path(M7)
    install_pylnk3_stub()
    try:
        import pyuac
        if not pyuac.isUserAdmin():
            print("[提权] 需要管理员权限注入输入，请在弹出的 UAC 对话框点“是”")
            pyuac.runAsAdmin()
            sys.exit(0)
    except ImportError:
        pass

    # Sprint A-3：硬门槛——提权流程后仍非管理员 → 直接退出，不继续测 click
    from tools.input_privilege_check import is_admin
    if not is_admin():
        print("[FAIL] INPUT_PRIVILEGE：需要管理员权限（UIPI 会拦截 SendInput）")
        print("       先运行: python tools/input_privilege_check.py 确认 READY")
        sys.exit(2)

    RESULT_FILE.unlink(missing_ok=True)
    os.chdir(M7)
    sys.path.insert(0, str(M7))
    sys.path.insert(0, str(ROOT))

    from module.automation import auto
    from module.ocr import ocr
    from runtime.win_capture import find_game_window
    from runtime.failure_report import FailureReporter

    reporter = FailureReporter()
    game = find_game_window()
    if game is None:
        print("[FAIL] 未找到游戏窗口")
        sys.exit(1)

    out_dir = ROOT / "ingest" / "raw" / "frames" / "live"
    out_dir.mkdir(parents=True, exist_ok=True)

    # —— 照抄 March7th 链路：PrintWindow 后台截图 + screenshot_pos 绝对换算 ——
    shot = auto.take_screenshot()
    if not shot:
        print("[FAIL] auto.take_screenshot 失败")
        sys.exit(1)
    img, screenshot_pos, scale_factor = shot
    pos_left, pos_top, _, _ = screenshot_pos

    lines = ocr_lines(ocr, img)
    # #20-3.3：目标匹配收紧——"商店"包含匹配太宽（商店铺/商店公告会误点）。
    # 用 文本长度上限 + 相似度启发：精确"商店"或长度<=4 且含"商店"。
    target = None
    for txt, box in lines:
        t = (txt or "").strip()
        if "商店" in t and len(t) <= 4:
            target = (t, box)
            break
    if target is None:
        print(f"[FAIL] 画面中未找到“商店”按钮。OCR: {[t for t, _ in lines][:12]}")
        img.save(str(out_dir / "click_before.jpg"), "JPEG", quality=92)
        reporter.report("click_test_no_target", screenshot_path=str(out_dir / "click_before.jpg"),
                        context={"ocr_lines": [t for t, _ in lines][:20]},
                        detail="点击测试：未在画面中找到商店按钮")
        sys.exit(1)

    # #20-3.3：点击前保存证据（"看到什么不重要，要证明看到的是正确东西"）
    img.save(str(out_dir / "click_before.jpg"), "JPEG", quality=92)
    print("[ok] 点击前证据已保存 click_before.jpg")
    txt, box = target
    lx, ly = box_center(box)
    # BUG-22：换算收敛到平台层（单一实现，防 DPI 修一处漏一处）
    from runtime.platform.windows.coords import screenshot_to_screen
    px, py = screenshot_to_screen(lx, ly, screenshot_pos, scale_factor)
    print(f"[ok] 找到“{txt}” 截图内({lx:.0f},{ly:.0f}) + pos({pos_left},{pos_top}) → 绝对({px},{py})")

    # Sprint A-5：分步 PASS 记录（OCR/坐标/注入/UI响应 → G2 PASS）
    steps = {"ocr": "PASS", "coordinate": "PASS", "sendinput": "PENDING",
             "ui_response": "PENDING"}

    auto.mouse_click(int(px), int(py))
    print("[ok] mouse_click 已执行")
    steps["sendinput"] = "PASS"
    time.sleep(2.5)

    shot2 = auto.take_screenshot()
    img2 = shot2[0] if shot2 else None
    if img2 is not None:
        img2.save(str(out_dir / "click_after.jpg"), "JPEG", quality=92)
    lines2 = ocr_lines(ocr, img2) if img2 is not None else []
    texts2 = [t for t, _ in lines2]
    print(f"[after] OCR: {texts2[:15]}")

    shop_open = any(k in "".join(texts2) for k in ["购买", "商品", "礼包", "开拓者补给", "星际和平", "信用点", "余烬兑换"])
    steps["ui_response"] = "PASS" if shop_open else "FAIL"

    # Sprint A-5：汇总输出 + result.json 落盘（失败报告自动关联 session）
    import json
    result = {"window": "崩坏：星穹铁道", "target": txt,
              "physical": (px, py), "steps": steps,
              "g2": "PASS" if all(v == "PASS" for v in steps.values()) else "FAIL"}
    print("=" * 32)
    print("CLICK TEST")
    print(f"    window:     {result['window']}")
    print(f"    target:     {txt}")
    print(f"    ocr:        {steps['ocr']}")
    print(f"    coordinate: {steps['coordinate']}")
    print(f"    sendinput:  {steps['sendinput']}")
    print(f"    ui_response:{steps['ui_response']}")
    print(f"RESULT: G2 {result['g2']}")
    print("=" * 32)
    (out_dir / "click_test_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not shop_open:
        if img2 is not None:
            reporter.report("click_no_response", screenshot_path=str(out_dir / "click_after.jpg"),
                            context={"clicked_text": txt, "physical": (px, py),
                                     "ocr_after": texts2[:20]},
                            detail="点击测试：点击后 UI 未变化")

    auto.press_key("esc", wait_time=1.0)
    print("[ok] esc 已按，恢复菜单")


if __name__ == "__main__":
    main()

```
