import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7 = ROOT / "March7thAssistant"


def require_m7():
    if not (M7 / "module").exists():
        print("未找到 March7thAssistant，请确认其位于 world_executor/March7thAssistant")
        sys.exit(1)
    cfg_file = M7 / "config.yaml"
    if not cfg_file.exists():
        example = M7 / "assets" / "config" / "config.example.yaml"
        if example.exists():
            cfg_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[setup] 已从 example 生成 {cfg_file.name}")
        else:
            print("缺少 config.example.yaml")
            sys.exit(1)
    sys.path.insert(0, str(M7))


def main():
    require_m7()
    print("[smoke] March7thAssistant 依赖导入中 ...")
    from module.automation import auto
    from module.ocr import ocr

    print(f"[smoke] window_title = {auto.window_title}")

    result = auto.take_screenshot()
    if result is None:
        print("[FAIL] take_screenshot 失败（游戏未启动或窗口未找到）")
        sys.exit(1)
    screenshot, pos, scale = result
    print(f"[ok] take_screenshot  {screenshot.shape} scale={scale}")

    found = auto.find_text_element("收容舱段", ["收容", "舱段"], need_ocr=True, relative=True)
    if found:
        text, pos = found
        print(f"[ok] OCR find_text_element -> {text} @ {pos}")
    else:
        print("[warn] OCR 未找到目标文本（可能不在该界面）")

    from module.ocr import RapidOCR

    ocr_engine = RapidOCR(mode=auto.ocr_mode)
    raw = auto.screenshot
    try:
        text, elapse = ocr_engine(raw)
        lines = [t for t, *_ in text] if text else []
        print(f"[ok] RapidOCR {len(lines)} 行: {lines[:8]}")
    except Exception as e:
        print(f"[warn] RapidOCR 失败: {e}")

    print("[smoke] 全部完成")


if __name__ == "__main__":
    main()
