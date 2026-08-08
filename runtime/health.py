"""运行时健康检查（Capability Check）：启动前确认各通道可用，失败可提前 pause。"""


def check_health(verbose=False):
    result = {
        "window": False,
        "capture": False,
        "ocr": False,
        "vlm": False,
        "input": False,
    }
    errors = {}

    # 1. 窗口锁定
    try:
        from runtime.win_capture import find_game_window
        game = find_game_window()
        result["window"] = game is not None
        if not game:
            errors["window"] = "未找到可见的游戏窗口"
    except Exception as e:
        errors["window"] = f"{type(e).__name__}: {e}"

    # 2. 截屏
    if result["window"]:
        try:
            from runtime.win_capture import capture_game_foreground
            img = capture_game_foreground(game)
            result["capture"] = img.size[0] > 0
            if not result["capture"]:
                errors["capture"] = "截图尺寸为空"
        except Exception as e:
            errors["capture"] = f"{type(e).__name__}: {e}"

    # 3. OCR（RapidOCR 已缓存模型，只验证导入）
    try:
        from runtime.input.march7th_backend import M7_ROOT
        import sys
        if str(M7_ROOT) not in sys.path:
            sys.path.insert(0, str(M7_ROOT))
        from module.ocr import ocr
        result["ocr"] = ocr is not None
    except Exception as e:
        errors["ocr"] = f"{type(e).__name__}: {e}"

    # 4. VLM（配置可达性）
    try:
        from runtime.observers.vlm_vision import VLMVisionObserver
        obs = VLMVisionObserver()
        result["vlm"] = obs.provider is not None
        if not result["vlm"]:
            errors["vlm"] = "VLM provider 未初始化"
    except Exception as e:
        errors["vlm"] = f"{type(e).__name__}: {e}"

    # 5. 输入注入（SendInput 探测：移动光标并回读）
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        r = user32.SetCursorPos(100, 100)
        pt = wintypes.POINT()
        time.sleep(0.1)
        user32.GetCursorPos(ctypes.byref(pt))
        if r and abs(pt.x - 100) < 50 and abs(pt.y - 100) < 50:
            result["input"] = True
        else:
            errors["input"] = "uipi_block: 输入注入被拒绝（需管理员权限）"
    except Exception as e:
        errors["input"] = f"{type(e).__name__}: {e}"

    import time
    if verbose:
        for k, v in result.items():
            mark = "OK" if v else "FAIL"
            print(f"  [{mark}] {k:8} {errors.get(k, '')}")
    return {"capability": result, "errors": errors, "all_ok": all(result.values())}
