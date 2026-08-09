import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs" / "live_fg.log"


def _log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(m + "\n")
    print(m)


def main():
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        import pyuac
        pyuac.runAsAdmin()
        sys.exit(0)
    from runtime.drivers.march7th.window import find_game_window
    from runtime.win_capture import set_foreground_with_retry
    game = find_game_window()
    if game is None:
        _log("[FAIL] 无游戏窗口")
        return
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    _log(f"激活前 前台={hex(fg)} 游戏={hex(game['hwnd'])}")
    ok = set_foreground_with_retry(game["hwnd"])
    fg2 = user32.GetForegroundWindow()
    _log(f"set_foreground_with_retry={ok} 前台={hex(fg2)} 命中={fg2 == game['hwnd']}")


if __name__ == "__main__":
    main()
