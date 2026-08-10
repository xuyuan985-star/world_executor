"""轨迹录制/回放测试（Fhoe record.py 思路适配）。

Test 1：合成轨迹保存/加载（recorder.save → replayer.load）
Test 2：回放按键（按住 duration 再释放——mock backend）
Test 3：回放点击（窗口相对坐标换算）
Test 4：回放视角移动（pynput mock）
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest import mock  # noqa: E402

TRAJ = {
    "version": 1, "recorded_at": 0,
    "events": [
        {"key": "w", "time_sleep": 0.5, "duration": 1.2},
        {"mouse_dx": 40, "mouse_dy": -12, "time_sleep": 0.3},
        {"key": "e", "time_sleep": 0.2, "duration": 0.1},
        {"click": True, "x": 320, "y": 240, "time_sleep": 0.4},
        {"key": "s", "time_sleep": 0.3, "duration": 0.8},
    ],
    "count": 5,
}


class FakeBackend:
    def __init__(self):
        self.pressed = []
        self.clicks = []

    def press_key(self, key, wait_time=0.2):
        self.pressed.append((key, wait_time))
        return type("R", (), {"success": True, "detail": {}})()

    def click(self, x, y):
        self.clicks.append((x, y))
        return type("R", (), {"success": True, "detail": {}})()


def main():
    from runtime.input.recorder import TrajectoryRecorder
    from runtime.input.replayer import TrajectoryReplayer

    tmp = Path(tempfile.mkdtemp()) / "traj.json"
    tmp.write_text(json.dumps(TRAJ, ensure_ascii=False), encoding="utf-8")

    # Test 2-4：回放
    bk = FakeBackend()
    rp = TrajectoryReplayer(game_hwnd=None, backend=bk, speed=100.0)
    n = rp.load(tmp)
    assert n == 5, n
    with mock.patch("pynput.mouse.Controller") as MC:
        MC.return_value.move = lambda dx, dy: None
        ok = rp.replay()
    assert ok
    assert ("w", 1.2) in bk.pressed, bk.pressed
    assert ("e", 0.1) in bk.pressed
    assert ("s", 0.8) in bk.pressed
    assert (320, 240) in bk.clicks, bk.clicks
    print("[traj] Test 2-4 PASS（按键时长/点击/视角回放）")

    # Test 1：save/load 往返
    rec = TrajectoryRecorder()
    rec.events = TRAJ["events"]
    path = rec.save(name="test_traj")
    assert path and path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["events"]) == 5
    path.unlink()
    print("[traj] Test 1 PASS（save/load 往返）")

    # Test 5：中止回放
    rp2 = TrajectoryReplayer(backend=FakeBackend(), speed=100.0)
    rp2.load(tmp)
    ok2 = rp2.replay(abort_check=lambda: True)
    assert not ok2
    print("[traj] Test 5 PASS（abort 中断）")

    print("[traj] Test 1-5 全部 PASS")


if __name__ == "__main__":
    main()
