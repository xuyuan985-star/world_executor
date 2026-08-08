"""运行时健康检查（Capability Check）：启动前确认各通道可用，失败可提前 pause。

输入健康分三级（v0.12.1）：
  L0 cursor_move     SetCursorPos → GetCursorPos 回读（注入通道）
  L1 send_input      SendInput 事件注入返回（事件级权限，UIPI）
  L2 game_response   按 ESC → 截图 → 画面变化/OCR 命中（游戏是否接受输入）
"""


def check_health(verbose=False, game_required=True):
    result = {
        "window": False,
        "capture": False,
        "ocr": False,
        "vlm": False,
        "input": False,
        "input_l0": False,
        "input_l1": False,
        "input_l2": False,
    }
    errors = {}

    import time

    # 1. 窗口锁定（driver.window 可见窗口枚举）
    try:
        from runtime.drivers.march7th.window import find_game_window
        game = find_game_window()
        result["window"] = game is not None
        if not game:
            errors["window"] = "未找到可见的游戏窗口"
    except Exception as e:
        errors["window"] = f"{type(e).__name__}: {e}"

    # 2. 截屏（PrintWindow 后台截图，March7th 通道）
    if result["window"]:
        try:
            from runtime.drivers.march7th.vision import March7thVision
            vision = March7thVision()
            shot = vision.take_screenshot()
            result["capture"] = shot is not None and shot[0].size[0] > 0
            if not result["capture"]:
                errors["capture"] = "后台截图为空"
        except Exception as e:
            errors["capture"] = f"{type(e).__name__}: {e}"

    # 3. OCR（RapidOCR 模型可用）
    try:
        from runtime.drivers.march7th.vision import March7thVision
        vision = March7thVision()
        result["ocr"] = vision.ocr is not None
        if not result["ocr"]:
            errors["ocr"] = "OCR 引擎未初始化"
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

    # 5. 输入健康分级
    try:
        import ctypes
        from ctypes import wintypes

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_ulong)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()

        # L0: 光标移动回读
        try:
            r = user32.SetCursorPos(100, 100)
            pt = wintypes.POINT()
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            result["input_l0"] = bool(r) and abs(pt.x - 100) < 50 and abs(pt.y - 100) < 50
            if not result["input_l0"]:
                errors["input_l0"] = "光标回读不一致（注入通道异常）"
        except Exception as e:
            errors["input_l0"] = f"{type(e).__name__}: {e}"

        # L1: SendInput 事件注入（UIPI 拦截时 ret=0）
        try:
            inp = INPUT()
            inp.type = 0
            inp.mi.dwFlags = 0x0001  # MOUSEEVENTF_MOVE，dx=dy=0 无副作用
            ret = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            result["input_l1"] = ret == 1
            if not result["input_l1"]:
                errors["input_l1"] = "uipi_block: SendInput 被拒绝（需管理员权限）"
        except Exception as e:
            errors["input_l1"] = f"{type(e).__name__}: {e}"

        # L2: 游戏响应探测（InputProbe，仅游戏窗口存在时）
        # 判据：以"画面变化显著"为主，OCR 命中菜单词为辅。
        # 不绑定 ESC 的行为语义：ESC 可能被剧情/战斗/UI 状态吃掉——
        # 关键判据是"按任意输入后游戏画面是否响应"，词表可配置。
        result["input_l2"] = None  # 未测
        if result["window"] and result["capture"]:
            try:
                from runtime.drivers.march7th.vision import March7thVision
                vision = March7thVision()
                import numpy as np
                img0, _, _ = vision.take_screenshot()
                arr0 = np.asarray(img0).astype(int)
                vision.auto.press_key("esc", wait_time=0.8)
                time.sleep(1.2)
                img1, _, _ = vision.take_screenshot()
                arr1 = np.asarray(img1).astype(int)
                diff = float(np.abs(arr1 - arr0).mean())
                texts = [t for t, _ in vision.ocr_lines()]
                hit = any(k in "".join(texts) for k in ["设置", "菜单", "esc", "ESC", "返回"])
                result["input_l2"] = diff > 2.0 or hit
                if not result["input_l2"]:
                    errors["input_l2"] = f"游戏未响应输入（画面变化 {diff:.1f}，OCR 未命中菜单词）"
            except Exception as e:
                result["input_l2"] = False
                errors["input_l2"] = f"{type(e).__name__}: {e}"

        result["input"] = bool(result["input_l0"] and result["input_l1"] and
                               (result["input_l2"] is None or result["input_l2"]))
    except Exception as e:
        errors["input"] = f"{type(e).__name__}: {e}"

    if verbose:
        for k, v in result.items():
            if v is None:
                continue
            mark = "OK" if v else "FAIL"
            print(f"  [{mark}] {k:8} {errors.get(k, '')}")
    return {"capability": result, "errors": errors, "all_ok": all(
        v for k, v in result.items() if k not in ("input_l2",))}
