"""像素差分验证测试（借鉴 GameCLI-Agent 机制适配）。

Test 1：pixel_diff 单元（相同帧/差异帧/nudge 序列）
Test 2：_click_with_diff_verify——点击后画面变化 → diff_verified 成功
Test 3：_click_with_diff_verify——未变化 → nudge 重试后变化（nudged 标记）
Test 4：_click_with_diff_verify——一直未变化 → nudge_exhausted 失败
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402


class FrameSeqVision:
    """按调用次数返回截图的 FakeVision（测试差分验证）。"""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def take_screenshot(self, crop=None):
        f = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return (f, (0, 0, 100, 100), 1.0)

    def to_absolute(self, nx, ny):
        return int(nx * 100), int(ny * 100)


class FakeInput:
    name = "fake"

    def __init__(self, results):
        self.results = list(results)
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))
        return type("R", (), {"success": bool(self.results.pop(0)),
                              "detail": {}})()


def make_frame(seed, bright=None):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    if bright:
        a[40:60, 40:60] = 255
    return Image.fromarray(a)


def main():
    from runtime.pixel_diff import images_different, nudge_offsets

    # Test 1：单元
    a = make_frame(1)
    assert not images_different(a, a)[0]
    b = make_frame(1, bright=True)
    assert images_different(a, b)[0]
    assert len(nudge_offsets()) >= 32
    print("[pixel_diff] Test 1 PASS（单元）")

    # Test 2：点击后画面变化 → 成功
    from runtime.step_executor import RealExecutor
    from unittest import mock

    ex = object.__new__(RealExecutor)
    ex._input_override = FakeInput([True])
    ex._driver = mock.MagicMock()
    ex.driver.vision = FrameSeqVision([make_frame(1), make_frame(1, bright=True)])
    r = ex._click_with_diff_verify(50, 50, "chest_A", "tpl.png", wait_seconds=0)
    assert r.success and r.detail.get("diff_verified") is True, r.detail
    print("[pixel_diff] Test 2 PASS（点击→变化→diff_verified）")

    # Test 3：未变化 → nudge 重试后变化
    ex3 = object.__new__(RealExecutor)
    # 点击序列：首次点击后不变（帧2=帧1），nudge 点击后变化
    ex3._input_override = FakeInput([True, True])
    ex3._driver = mock.MagicMock()
    ex3.driver.vision = FrameSeqVision([make_frame(1), make_frame(1),
                                        make_frame(1, bright=True)])
    r3 = ex3._click_with_diff_verify(50, 50, "chest_A", "tpl.png", wait_seconds=0)
    assert r3.success and r3.detail.get("nudged"), r3.detail
    assert len(ex3.input.clicks) >= 2
    print(f"[pixel_diff] Test 3 PASS（nudge 重试→nudged {r3.detail.get('nudged')}）")

    # Test 4：一直未变化 → nudge_exhausted
    ex4 = object.__new__(RealExecutor)
    ex4._input_override = FakeInput([True] * 40)
    ex4._driver = mock.MagicMock()
    ex4.driver.vision = FrameSeqVision([make_frame(1)] * 40)
    r4 = ex4._click_with_diff_verify(50, 50, "chest_A", "tpl.png", wait_seconds=0)
    assert r4.success and r4.detail.get("nudge_exhausted") is True, r4.detail
    print("[pixel_diff] Test 4 PASS（nudge 耗尽→标记失败）")

    print("[pixel_diff] Test 1-4 全部 PASS")


if __name__ == "__main__":
    main()
