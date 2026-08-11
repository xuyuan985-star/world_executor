import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M7 = (ROOT / "m7" if (ROOT / "m7" / "main.py").exists() else ROOT.parent / "March7thAssistant")


def main():
    from security.quarantine import install_pylnk3_stub, require_m7_path
    require_m7_path(M7)
    install_pylnk3_stub()
    os.chdir(M7)
    sys.path.insert(0, str(M7))
    sys.path.insert(0, str(ROOT))
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()  # #18：DPI context 进程早期设置

    from module.automation import auto

    from runtime.win_capture import find_game_window, capture_game_foreground

    out_dir = ROOT / "ingest" / "raw" / "frames" / "live"
    out_dir.mkdir(parents=True, exist_ok=True)

    game = find_game_window()
    if game is None:
        print("[FAIL] 未找到可见游戏窗口")
        sys.exit(1)
    img = capture_game_foreground(game)
    path = out_dir / f"live_{int(time.time())}.jpg"
    img.save(path, "JPEG", quality=92)
    print(f"[ok] 截图已保存 {path} ({img.size})")

    from runtime.observers.vlm_vision import VLMVisionObserver
    obs = VLMVisionObserver()

    rooms = ["基座舱段大厅", "基座舱段走廊", "收容舱段", "空间站入口", "其他星球", "未知场景"]
    r1 = obs.observe_room(str(path), rooms)
    print(f"[vlm] room#1: {r1}")

    loc1 = obs.locate_target(str(path), "普通宝箱（金色/木箱实体，可互动的宝箱模型）")
    print(f"[vlm] locate#1: {loc1}")

    time.sleep(2.5)
    img2 = capture_game_foreground(game)
    path2 = out_dir / f"live_{int(time.time())}.jpg"
    img2.save(path2, "JPEG", quality=92)

    r2 = obs.observe_room(str(path2), rooms)
    print(f"[vlm] room#2: {r2}")
    loc2 = obs.locate_target(str(path2), "普通宝箱（金色/木箱实体，可互动的宝箱模型）")
    print(f"[vlm] locate#2: {loc2}")

    found1 = loc1.get("found") is True
    found2 = loc2.get("found") is True
    if not found1 and not found2:
        print(f"[判定] chest_state = opened（两次独立观测均无宝箱实体，{len(rooms)} 候选房间含 r2.room={r2.get('room')}）")
    elif found1 and found2:
        print(f"[判定] chest_state = present（两次观测均见宝箱）")
    else:
        print(f"[判定] chest_state = unknown（两次观测不一致，需人工确认）")


if __name__ == "__main__":
    main()
