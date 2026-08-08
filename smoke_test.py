import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M7 = ROOT.parent / "March7thAssistant"


def install_pylnk3_stub():
    """pylnk3 为被投毒过的 PyPI 包；March7th 仅在解析 .lnk 快捷方式时使用，
    我们不做游戏启动流程，故注入 stub 防止下载真包并避免执行 config 内的混淆 payload。"""
    if sys.modules.get("pylnk3"):
        return
    stub = types.ModuleType("pylnk3")

    class Lnk:
        # #33：补齐常用属性，避免后续代码访问 Lnk().path 等直接炸
        path = ""
        arguments = ""
        work_dir = ""

        def __init__(self, f):
            self.path = str(f)

    stub.Lnk = Lnk
    sys.modules["pylnk3"] = stub
    print("[security] pylnk3 stub 已注入（跳过被投毒包 + 混淆 payload）")


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
    os.chdir(M7)
    sys.path.insert(0, str(M7))
    install_pylnk3_stub()


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
    w, h = screenshot.size if hasattr(screenshot, "size") else screenshot.shape[:2][::-1]
    print(f"[ok] take_screenshot  {w}x{h} scale={scale}")

    found = auto.find_text_element("收容舱段", ["收容", "舱段"], need_ocr=True, relative=True)
    if found:
        text, pos = found
        print(f"[ok] OCR find_text_element -> {text} @ {pos}")
    else:
        print("[warn] OCR 未找到目标文本（可能不在该界面）")

    from module.ocr import ocr as ocr_engine

    # #22：RapidOCR 要求 ndarray，统一 np.asarray（与 coords_calibrate 一致）
    import numpy as np
    raw = np.asarray(screenshot)
    try:
        result = ocr_engine.run(raw)
        lines = [t["txt"] for t in result if isinstance(t, dict) and t.get("txt")] if result else []
        print(f"[ok] OCR 引擎 {len(lines)} 行: {lines[:8]}")
    except Exception as e:
        print(f"[warn] OCR 引擎失败: {e}")

    print("[smoke] 全部完成")


if __name__ == "__main__":
    main()
