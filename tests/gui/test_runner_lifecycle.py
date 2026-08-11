# -*- coding: utf-8 -*-
"""任务中心 QProcess 子进程模式回归测试（0.6.0 回滚后）。

背景：0.5.0 曾改为进程内 QThread 集成（import main 同进程）——反复
0xC0000409 崩溃（Qt 析构运行中 QThread）。0.6.0 回滚为 QProcess 子进程：
m7 在独立进程跑（cwd/单例/配置零冲突，kill 即停），结构性规避崩溃。

本测试不启动真实 m7（避免碰游戏），验证：
1. 缺 M7 时 fail-closed（明确报错 + finished(1)，不静默）
2. 未运行时 stop 安全
3. running 状态初值
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication

_app = None


def _app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


class TaskProcessFailClosedTest(unittest.TestCase):

    def test_missing_m7_fails_closed(self):
        """M7_ROOT 不存在 → 明确错误日志 + task_finished(1) + start 返回 False。"""
        _app()
        from gui.tasks.runner import TaskProcess
        proc = TaskProcess("screen_test")
        logs = []
        finished = []
        proc.log_line.connect(lambda s: logs.append(s))
        proc.task_finished.connect(lambda c: finished.append(c))
        # 模拟管理员环境（旧版 fail-closed 先查权限——非管理员提前拒绝）
        with mock.patch("ctypes.windll.shell32.IsUserAnAdmin",
                        return_value=True), \
             mock.patch("gui.tasks.catalog.M7_ROOT") as fake:
            fake.exists.return_value = False
            ok = proc.start()
        self.assertFalse(ok, "缺 M7 时 start 必须返回 False（fail-closed）")
        self.assertTrue(any("未找到 March7thAssistant" in s for s in logs),
                        f"应有明确错误提示，实际: {logs}")
        self.assertEqual(finished, [1], "应发 task_finished(1)")

    def test_not_running_stop_safe(self):
        """未运行时 stop 返回 False（不异常）。"""
        _app()
        from gui.tasks.runner import TaskProcess
        proc = TaskProcess("screen_test")
        self.assertFalse(proc.running)
        self.assertFalse(proc.stop(), "未运行 stop 应返回 False")

    def test_initial_running_false(self):
        """初始 running=False。"""
        _app()
        from gui.tasks.runner import TaskProcess
        proc = TaskProcess("screen_test")
        self.assertFalse(proc.running)


if __name__ == "__main__":
    unittest.main(verbosity=2)
