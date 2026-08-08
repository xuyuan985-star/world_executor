import ctypes
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M7 = ROOT.parent / "March7thAssistant"

ROOM_CANDIDATES = ["基座舱段", "收容舱段", "支援舱段", "禁闭舱段", "黑塔空间站其他区域", "雅利洛VI", "仙舟", "匹诺康尼", "未知场景"]


def install_pylnk3_stub():
    import types
    if sys.modules.get("pylnk3"):
        return
    stub = types.ModuleType("pylnk3")
    class Lnk:
        def __init__(self, f):
            self.work_dir = ""
    stub.Lnk = Lnk
    sys.modules["pylnk3"] = stub


def window_info():
    import win32gui
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    g = win32gui.FindWindow(None, "崩坏：星穹铁道")
    info = {
        "foreground": title or "(no title)",
        "game_hwnd": g,
        "game_visible": bool(ctypes.windll.user32.IsWindowVisible(g)) if g else False,
        "game_minimized": bool(ctypes.windll.user32.IsIconic(g)) if g else False,
    }
    if g:
        cl = win32gui.GetClientRect(g)
        info["game_client_rect"] = (cl[2], cl[3])
    return info


def capture_screen():
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        from PIL import Image
        return Image.frombytes("RGB", shot.size, shot.rgb)


def main(loop_seconds=15, max_rounds=None):
    install_pylnk3_stub()
    os.chdir(M7)
    sys.path.insert(0, str(M7))
    sys.path.insert(0, str(ROOT))
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()  # #18：DPI context 进程早期设置

    from runtime.observers.vlm_vision import VLMVisionObserver
    from runtime.failure_report import FailureReporter
    from runtime.win_capture import capture_game_foreground, find_game_window

    obs = VLMVisionObserver()
    reporter = FailureReporter()
    out_dir = ROOT / "ingest" / "raw" / "frames" / "live"
    out_dir.mkdir(parents=True, exist_ok=True)

    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        stamp = int(time.time())
        try:
            win = window_info()
            game = find_game_window()
            print(f"\n=== 监控 #{rounds} @ {time.strftime('%H:%M:%S')} ===")
            print(f"  前台窗口: {win['foreground']} | 可见游戏窗口: {game['client'] if game else '无'}")

            try:
                img = capture_game_foreground(game)
                src = "game_window"
            except Exception as e:
                img = capture_screen()
                src = f"screen(fallback:{e})"
                reporter.report("game_window_activation_failed",
                                screenshot_path=path if "path" in dir() else None,
                                context={"window": win, "game": game},
                                detail=f"无法激活游戏窗口: {e}。请手动点击游戏窗口切到前台。")
            path = out_dir / f"{src}_{stamp}.jpg"
            img.save(path, "JPEG", quality=90)
            print(f"  [ok] 捕获 {src} {img.size}")

            analysis = obs.observe_room(str(path), ROOM_CANDIDATES)
            locate = obs.locate_target(str(path), "普通宝箱（金色/木箱实体，可互动的宝箱模型）")

            what = analysis.get("ui_state")
            room = analysis.get("room")
            found = locate.get("found") is True
            conf = analysis.get("confidence") or 0.0
            print(f"  [vlm] 画面={what} room={room} conf={conf} 宝箱={found}")

            black_tower_rooms = [r for r in ROOM_CANDIDATES if "舱段" in r or "黑塔" in r]
            room_hit = room in black_tower_rooms and conf >= 0.4
            game_ui = what in ("game", "loading", "menu", "dialogue", "combat")
            game_in_screen = room_hit or (game_ui and conf >= 0.5)

            if game is None:
                reporter.report("game_window_not_found",
                                screenshot_path=path,
                                context={"window": win},
                                vlm_outputs={"room": analysis, "locate": locate},
                                detail="未找到可见的游戏窗口")
            elif not game_in_screen:
                reporter.report("screen_not_game",
                                screenshot_path=path,
                                context={"window": win, "game": game},
                                vlm_outputs={"room": analysis, "locate": locate},
                                detail=f"捕获源={src}，画面不是游戏: {what}/{room} conf={conf}")
        except Exception as e:
            reporter.report("monitor_exception",
                            context={"round": rounds},
                            detail=f"{type(e).__name__}: {e}")
        time.sleep(loop_seconds)


if __name__ == "__main__":
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(max_rounds=rounds)
