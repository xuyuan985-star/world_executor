"""游戏拉起测试（借鉴 m7 LocalGameController.start_game_process 适配）。

Test 1：窗口已在 → already_running（不启动）
Test 2：窗口缺失 → 启动进程 → 等窗口成功 → started
Test 3：窗口缺失且等窗口超时 → False（原因含超时）
Test 4：game_executable 读取 m7 config.yaml
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest import mock  # noqa: E402


def main():
    from runtime.platform.windows import game_launcher as gl

    # Test 4：game_executable 读 m7 config
    exe = gl.game_executable()
    assert exe and "StarRail" in exe, exe
    print(f"[launcher] Test 4 PASS（game_path={exe}）")

    # Test 1：窗口在 → already_running，不调启动
    # 注意：game_launcher 内是函数级 import win_capture——mock 须打源头
    with mock.patch("runtime.win_capture.find_game_window",
                    return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(gl, "launch_game_process") as m_launch:
        ok, why = gl.ensure_game_launched(wait_seconds=3, auto_enter=False)
    assert ok and why == "already_running", (ok, why)
    m_launch.assert_not_called()
    print("[launcher] Test 1 PASS（窗口在 → 不启动）")

    # Test 2：窗口缺失 → 启动 → 等窗口成功 → started
    seq = {"n": 0}

    def fake_find(*a, **k):
        seq["n"] += 1
        return {"hwnd": 1, "client": (1920, 1080)} if seq["n"] >= 3 else None

    with mock.patch("runtime.win_capture.find_game_window",
                    side_effect=fake_find), \
            mock.patch.object(gl, "launch_game_process", return_value=True) as m_launch, \
            mock.patch.object(gl, "click_enter_if_present", return_value=True):
        ok, why = gl.ensure_game_launched(wait_seconds=10, auto_enter=True)
    assert ok and why == "started", (ok, why)
    m_launch.assert_called_once()
    print("[launcher] Test 2 PASS（窗口缺失 → 启动 → 等窗口 → started）")

    # Test 3：窗口一直缺失 → 超时 False
    with mock.patch("runtime.win_capture.find_game_window",
                    return_value=None), \
            mock.patch.object(gl, "launch_game_process", return_value=True):
        ok, why = gl.ensure_game_launched(wait_seconds=0.5, auto_enter=False)
    assert not ok and "超时" in why, (ok, why)
    print("[launcher] Test 3 PASS（等窗口超时 → False）")

    # Test 3b：启动失败 → False
    with mock.patch("runtime.win_capture.find_game_window",
                    return_value=None), \
            mock.patch.object(gl, "launch_game_process", return_value=False):
        ok, why = gl.ensure_game_launched(wait_seconds=0.5, auto_enter=False)
    assert not ok and "启动失败" in why, (ok, why)
    print("[launcher] Test 3b PASS（启动失败 → False）")

    print("[launcher] Test 1-4 全部 PASS")


if __name__ == "__main__":
    main()
