"""Bug 409/411：坐标转换单元测试（多分辨率/DPI/窗口移动）。

覆盖：1080p/1440p/4K 归一化换算、DPI 125%、窗口偏移、窗口移动后坐标。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.platform.windows.coords import (CoordinateSpace,
                                             logical_to_physical,
                                             physical_to_logical,
                                             screenshot_to_screen)


class TestCoordinateSpace(unittest.TestCase):
    def test_1080p(self):
        # Bug 409：1080p 基准——0.5,0.5 → (960,540)
        space = CoordinateSpace.from_scale_factor(1.0)
        self.assertEqual(logical_to_physical(960, 540, space), (960, 540))
        self.assertEqual(physical_to_logical(960, 540, space), (960, 540))

    def test_1440p(self):
        # 1440p：逻辑 1920x1080 → 物理 2560x1440（scale=4/3）
        space = CoordinateSpace.from_scale_factor(4 / 3)
        px, py = logical_to_physical(960, 540, space)
        self.assertEqual((px, py), (1280, 720))
        lx, ly = physical_to_logical(1280, 720, space)
        self.assertEqual((lx, ly), (960, 540))

    def test_4k(self):
        # 4K：scale=2 —— 逻辑半屏 → 物理全屏
        space = CoordinateSpace.from_scale_factor(2.0)
        px, py = logical_to_physical(960, 540, space)
        self.assertEqual((px, py), (1920, 1080))

    def test_dpi125(self):
        # Bug 393：125% DPI——client 1536x864（逻辑）→ 物理 1920x1080
        space = CoordinateSpace.from_scale_factor(1.25)
        px, py = logical_to_physical(768, 432, space)
        self.assertEqual((px, py), (960, 540))

    def test_scale_zero_guard(self):
        # scale<=0 不做除法（防除零）
        space = CoordinateSpace(scale=0)
        self.assertEqual(physical_to_logical(100, 100, space), (100, 100))

    def test_window_offset(self):
        # Bug 411：窗口移动/偏移——截图内坐标 + 窗口左上角绝对位置
        # 窗口在 (100, 50) 位置，截图内 (500, 300)，scale=1
        self.assertEqual(screenshot_to_screen(500, 300, (100, 50, 2020, 1130)),
                         (600, 350))

    def test_window_offset_scaled(self):
        # 窗口偏移 + 缩放（BUG-22 场景）
        self.assertEqual(screenshot_to_screen(500, 300, (100, 50, 0, 0), scale=2.0),
                         (350, 200))


if __name__ == "__main__":
    unittest.main()
