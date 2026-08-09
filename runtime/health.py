"""运行时健康检查（Capability Check）：启动前确认各通道可用，失败可提前 pause。

输入健康分三级（v0.12.1）：
  L0 cursor_move     SetCursorPos → GetCursorPos 回读（注入通道）
  L1 send_input      SendInput 事件注入返回（事件级权限，UIPI）
  L2 game_response   按 ESC → 截图 → 画面变化/OCR 命中（游戏是否接受输入）
"""


def check_health(verbose=False, game_required=True, input_probe=False):
    """隐藏 Bug 审查：input_probe 控制 L2 按键注入探测（默认关——
    会向游戏按 ESC，GUI 启动检测时不能打扰用户）。"""
    result = {
        "window": False,
        "capture": False,
        "ocr": False,
        "vlm": False,
        "foreground": False,
        "admin": False,
        "input": False,
        "input_l0": False,
        "input_l1": False,
        "input_l2": False,
    }
    errors = {}

    import time

    # 0. 管理员权限（SendInput/UIPI 前置条件）
    try:
        import ctypes
        result["admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        if not result["admin"]:
            errors["admin"] = "非管理员权限（SendInput 可能被 UIPI 拦截）"
    except Exception as e:
        errors["admin"] = f"{type(e).__name__}: {e}"

    # 1. 窗口锁定（driver.window 可见窗口枚举）
    try:
        from runtime.drivers.march7th.window import find_game_window
        game = find_game_window()
        result["window"] = game is not None
        if not game:
            errors["window"] = "未找到可见的游戏窗口"
        else:
            # 前台锁定：操作前游戏必须在前台（M1-A 输入前提）
            # 自动置顶：检测前先尝试激活游戏（用户要求"程序自动把游戏提置顶"）
            import ctypes
            try:
                from runtime.win_capture import set_foreground_with_retry
                set_foreground_with_retry(game["hwnd"])
                time.sleep(0.3)
            except Exception:
                pass
            fg = ctypes.windll.user32.GetForegroundWindow()
            result["foreground"] = fg == game["hwnd"]
            if not result["foreground"]:
                errors["foreground"] = f"游戏窗口不在前台 (0x{fg:x})"
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
            # dwExtraInfo 必须 ULONG_PTR（64 位下 c_size_t）——c_ulong 会致
            # 结构大小错误 SendInput 拒收（与 win32_backend 同款 64 位 bug，
            # 之前就是它导致真机点击 L1 误报 uipi_block）
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()

        # L0: 光标移动回读（GUI-2：探测后必须恢复原位——否则启动 GUI 鼠标跳左上角）
        try:
            saved_pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(saved_pt))
            r = user32.SetCursorPos(100, 100)
            pt = wintypes.POINT()
            time.sleep(0.1)
            user32.GetCursorPos(ctypes.byref(pt))
            result["input_l0"] = bool(r) and abs(pt.x - 100) < 50 and abs(pt.y - 100) < 50
            if not result["input_l0"]:
                errors["input_l0"] = "光标回读不一致（注入通道异常）"
            # 恢复原鼠标位置（探测副作用最小化）
            user32.SetCursorPos(saved_pt.x, saved_pt.y)
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
        # 隐藏 Bug：L2 会向游戏注入 ESC 键——GUI 启动的 HealthWorker 也会跑
        # check_health，用户正在游戏时会被按 ESC 打断（菜单/剧情/战斗）。
        # 按键注入探测默认关闭（input_probe=False），仅真机 gate 时开启。
        result["input_l2"] = None  # 未测
        if input_probe and result["window"] and result["capture"]:
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

    # Bug 252：依赖检查——ffmpeg / 磁盘空间 / 知识库
    try:
        import shutil
        result["ffmpeg"] = shutil.which("ffmpeg") is not None
        if not result["ffmpeg"]:
            errors["ffmpeg"] = "未找到 ffmpeg（抽帧/下载需要）"
    except Exception as e:
        result["ffmpeg"] = False
        errors["ffmpeg"] = f"{type(e).__name__}: {e}"
    try:
        import shutil
        from pathlib import Path
        usage = shutil.disk_usage(Path(__file__).resolve().parent.parent)
        free_mb = usage.free / (1024 * 1024)
        result["disk"] = free_mb > 500
        if not result["disk"]:
            errors["disk"] = f"磁盘剩余 {free_mb:.0f}MB < 500MB"
    except Exception as e:
        result["disk"] = False
        errors["disk"] = f"{type(e).__name__}: {e}"

    if verbose:
        for k, v in result.items():
            if v is None:
                continue
            mark = "OK" if v else "FAIL"
            print(f"  [{mark}] {k:8} {errors.get(k, '')}")
    return {"capability": result, "errors": errors, "all_ok": all(
        v for k, v in result.items() if k not in ("input_l2",))}