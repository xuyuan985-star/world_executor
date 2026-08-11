import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M7 = (ROOT / "m7" if (ROOT / "m7" / "main.py").exists() else ROOT.parent / "March7thAssistant")


def require_m7():
    from security.quarantine import install_pylnk3_stub, require_m7_path
    require_m7_path(M7)
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
    # BUG-27：DPI context 入口第一行（import module.automation 前，防读取窗口尺寸已迟）
    from runtime.platform.windows.privilege import init_dpi
    init_dpi()
    # #17：脚本退出/异常时恢复 cwd（March7th 运行期间必须 chdir，结束即还原）
    old = os.getcwd()
    try:
        require_m7()
        print("[smoke] March7thAssistant 依赖导入中 ...")
        from module.automation import auto
        from module.ocr import ocr

        print(f"[smoke] window_title = {auto.window_title}")

        # #20-3.1：截图/OCR 异常分类报告（CI 友好，禁止裸 traceback）
        try:
            shot_result = auto.take_screenshot()
        except Exception as e:
            print(f"[FAIL] category=capture exception={e!r}")
            sys.exit(1)
        if shot_result is None:
            print("[FAIL] category=capture take_screenshot 失败（游戏未启动或窗口未找到）")
            sys.exit(1)
        screenshot, pos, scale = shot_result
        w, h = screenshot.size if hasattr(screenshot, "size") else screenshot.shape[:2][::-1]
        print(f"[ok] take_screenshot  {w}x{h} scale={scale}")

        try:
            found = auto.find_text_element("收容舱段", ["收容", "舱段"], need_ocr=True, relative=True)
        except Exception as e:
            print(f"[FAIL] category=ocr exception={e!r}")
            sys.exit(1)
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
            ocr_result = ocr_engine.run(raw)
            lines = [t["txt"] for t in ocr_result if isinstance(t, dict) and t.get("txt")] if ocr_result else []
            print(f"[ok] OCR 引擎 {len(lines)} 行: {lines[:8]}")
        except Exception as e:
            print(f"[FAIL] category=ocr_engine exception={e!r}")
            sys.exit(1)

        print("[smoke] 全部完成")
    finally:
        os.chdir(old)


if __name__ == "__main__":
    main()
