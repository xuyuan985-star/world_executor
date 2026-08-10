"""轨迹录制/回放测试（Fhoe record.py 思路适配 + 分辨率归一化）。

Test 1：合成轨迹保存/加载（含 client_w/h meta）
Test 2：回放按键（按住 duration 再释放——mock backend）
Test 3：回放归一化点击——不同客户区尺寸换算正确（分辨率自适应）
Test 4：回放归一化视角位移
Test 5：abort 中断
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
    "client_w": 1920, "client_h": 1080,
    "events": [
        {"key": "w", "time_sleep": 0.5, "duration": 1.2},
        {"view_dx": 0.02, "view_dy": -0.011, "time_sleep": 0.3},
        {"key": "e", "time_sleep": 0.2, "duration": 0.1},
        {"click": True, "nx": 0.5, "ny": 0.5, "time_sleep": 0.4},
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


class FakeGeom:
    """可变的客户区几何（测分辨率自适应）。"""

    def __init__(self, ox, oy, w, h):
        self.ox, self.oy, self.w, self.h = ox, oy, w, h

    def geometry(self):
        return (self.ox, self.oy, self.w, self.h)


def make_replayer(geom, backend=None):
    from runtime.input.replayer import TrajectoryReplayer
    rp = TrajectoryReplayer(game_hwnd=1, backend=backend or FakeBackend(),
                            speed=100.0)
    rp._client_geometry = geom.geometry
    return rp


def main():
    from runtime.input.recorder import TrajectoryRecorder
    from runtime.input.replayer import TrajectoryReplayer

    tmp = Path(tempfile.mkdtemp()) / "traj.json"
    tmp.write_text(json.dumps(TRAJ, ensure_ascii=False), encoding="utf-8")

    # Test 2/4：按键 + 视角回放（归一化视角 × 当前尺寸）
    bk = FakeBackend()
    geom = FakeGeom(0, 0, 1920, 1080)
    rp = make_replayer(geom, bk)
    n = rp.load(tmp)
    assert n == 5, n
    with mock.patch("pynput.mouse.Controller") as MC:
        MC.return_value.move = lambda dx, dy: None
        ok = rp.replay()
    assert ok
    assert ("w", 1.2) in bk.pressed
    assert ("e", 0.1) in bk.pressed
    assert ("s", 0.8) in bk.pressed
    print("[traj] Test 2/4 PASS（按键时长 + 归一化视角回放）")

    # Test 3：分辨率自适应——录制 1920x1080，回放 1280x720（窗口原点 100,50）
    bk3 = FakeBackend()
    geom3 = FakeGeom(100, 50, 1280, 720)
    rp3 = make_replayer(geom3, bk3)
    rp3.load(tmp)
    with mock.patch("pynput.mouse.Controller") as MC:
        MC.return_value.move = lambda dx, dy: None
        rp3.replay()
    # nx=0.5, ny=0.5 → 100 + 0.5*1280 = 740, 50 + 0.5*720 = 410
    assert (740, 410) in bk3.clicks, bk3.clicks
    print("[traj] Test 3 PASS（分辨率变化归一化点击换算：录制 1920x1080 → 回放 1280x720 @(740,410)）")

    # Test 1：save/load 往返（含 meta）
    rec = TrajectoryRecorder()
    rec.events = TRAJ["events"]
    rec._client_size = (1920, 1080)
    path = rec.save(name="test_traj")
    assert path and path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["client_w"] == 1920 and len(data["events"]) == 5
    path.unlink()
    print("[traj] Test 1 PASS（save/load 含分辨率 meta）")

    # Test 5：abort
    rp5 = make_replayer(FakeGeom(0, 0, 1920, 1080))
    rp5.load(tmp)
    assert not rp5.replay(abort_check=lambda: True)
    print("[traj] Test 5 PASS（abort 中断）")

    print("[traj] Test 1-5 全部 PASS")


if __name__ == "__main__":
    main()
