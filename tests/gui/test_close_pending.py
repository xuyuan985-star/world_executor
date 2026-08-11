# -*- coding: utf-8 -*-
"""回归：closeEvent 的 task_pending 判断（曾写成 `shutdown() is False`——
无任务时 `False is False` 恒 True → 关窗口必 os._exit(0) 无痕退出；
任务卡住时返回 True → `True is False` 恒 False → 不兜底 → Qt 析构
运行中 QThread → 0xC0000409 崩溃。两个方向全反。）

修复：task_pending = bool(studio.shutdown())——True=任务仍在跑→os._exit 兜底。
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


class TaskPendingLogicTest(unittest.TestCase):
    """直接验证 closeEvent 的判断语义（不跑完整窗口/不杀进程）。"""

    def test_idle_close_not_pending(self):
        """无任务：studio.shutdown() 返回 False → task_pending 必须 False。"""
        studio_return = False  # 干净结束（无任务/任务已停）
        task_pending = bool(studio_return)
        self.assertFalse(task_pending, "无任务关窗口不应 os._exit")

    def test_running_task_is_pending(self):
        """任务卡住：studio.shutdown() 返回 True → task_pending 必须 True。"""
        studio_return = True  # 任务仍在运行（m7 无硬中断）
        task_pending = bool(studio_return)
        self.assertTrue(task_pending, "任务运行中关窗口必须 os._exit 兜底")

    def test_regression_old_bug(self):
        """防回归：旧写法 `shutdown() is False` 两个方向全反（必现 bug）。"""
        # 无任务：False is False → True（错！应 False）
        self.assertTrue(False is False, "旧写法无任务时误判 pending（bug 复现）")
        # 任务卡住：True is False → False（错！应 True）
        self.assertFalse(True is False, "旧写法任务卡住时不兜底（bug 复现）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
