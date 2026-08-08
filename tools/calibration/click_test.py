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
    # 截图内坐标 → 绝对屏幕坐标（>1920 截图时需除以 scale_factor 还原）
    px = pos_left + int(lx / scale_factor if scale_factor and scale_factor != 1 else lx)
    py = pos_top + int(ly / scale_factor if scale_factor and scale_factor != 1 else ly)
    print(f"[ok] 找到“{txt}” 截图内({lx:.0f},{ly:.0f}) + pos({pos_left},{pos_top}) → 绝对({px},{py})")

    auto.mouse_click(int(px), int(py))
    print("[ok] mouse_click 已执行")
    time.sleep(2.5)

    shot2 = auto.take_screenshot()
    img2 = shot2[0] if shot2 else None
    if img2 is not None:
        img2.save(str(out_dir / "click_after.jpg"), "JPEG", quality=92)
    lines2 = ocr_lines(ocr, img2) if img2 is not None else []
    texts2 = [t for t, _ in lines2]
    print(f"[after] OCR: {texts2[:15]}")

    shop_open = any(k in "".join(texts2) for k in ["购买", "商品", "礼包", "开拓者补给", "星际和平", "信用点", "余烬兑换"])
    if shop_open:
        print("[RESULT] 点击链路 PASS：商店界面已打开（识别→点击→UI响应）")
    else:
        print("[RESULT] 点击后画面无明显变化（可能点到菜单空白或点击未生效）")
        if img2 is not None:
            reporter.report("click_no_response", screenshot_path=str(out_dir / "click_after.jpg"),
                            context={"clicked_text": txt, "physical": (px, py),
                                     "ocr_after": texts2[:20]},
                            detail="点击测试：点击后 UI 未变化")

    auto.press_key("esc", wait_time=1.0)
    print("[ok] esc 已按，恢复菜单")


if __name__ == "__main__":
    main()
