"""m7 任务执行（进程内集成——用户要求：代码纳入而非子进程）。

架构（迁移自子进程模式的改进）：
- 主程序与 m7 同进程（统一 Python 3.14 环境——m7 官方要求 >=3.12）
- 任务在 QThread 跑：stub 注入 → import main → run_sub_task(action)
- 日志：m7 console handler 输出 sys.stderr——线程内重定向到队列，
  主线程轮询消费（本环境 QThread 信号不投递——沿用 _result 轮询模式）
- 停止：标记 stop_flag——m7 任务内部无检查点，单轮任务自然结束后退出
  （GUI 提示"停止请求已发送，当前步骤结束后退出"）
"""
import io
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, QObject, Signal


class _TaskThread(QThread):
    """进程内 m7 任务线程（结果写 _result，日志写 _log_lines——轮询消费）。"""

    def __init__(self, task_id, m7_root, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.m7_root = str(m7_root)
        self._result = None
        self._log_lines = []
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()

    def request_stop(self):
        self._stop_flag.set()

    def _log(self, line):
        if not line:
            return
        with self._lock:
            self._log_lines.append(line)
            if len(self._log_lines) > 2000:
                self._log_lines = self._log_lines[-2000:]

    def drain_logs(self):
        """主线程轮询取日志。"""
        with self._lock:
            lines = self._log_lines
            self._log_lines = []
            return lines

    def run(self):
        old_cwd = os.getcwd()
        old_stderr = sys.stderr
        try:
            # 1. pylnk3 stub（m7 module/config 混入 payload——不注入则崩）
            from security.quarantine import install_pylnk3_stub, require_m7_path
            require_m7_path(self.m7_root)
            install_pylnk3_stub(verbose=False)
            # 2. cwd/路径切到 m7（任务运行期需要——结束恢复）
            os.chdir(self.m7_root)
            sys.path.insert(0, self.m7_root)
            os.environ["MARCH7TH_DOCKER_STARTED"] = "true"
            # 3. 日志重定向：m7 console handler 写 sys.stderr → 队列
            stream = io.StringIO()
            sys.stderr = stream
            try:
                import main as m7main
                m7main.run_sub_task(self.task_id)
            finally:
                sys.stderr = old_stderr
                for line in stream.getvalue().splitlines():
                    self._log(line)
            self._result = ("done", 0)
        except Exception as e:
            self._result = ("err", f"{type(e).__name__}: {e}")
        finally:
            os.chdir(old_cwd)


class TaskProcess(QObject):
    """进程内任务执行器（接口兼容原 QProcess 版——TaskCenterPage 无感切换）。"""

    log_line = Signal(str)
    task_finished = Signal(int)
    task_started = Signal()

    def __init__(self, task_id, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._thread = None
        self._stopped_by_user = False

    @property
    def running(self):
        return self._thread is not None and self._thread.isRunning()

    def start(self):
        from gui.tasks.catalog import M7_ROOT

        if self.running:
            return False
        self._stopped_by_user = False
        if not M7_ROOT.exists():
            self.log_line.emit(f"[错误] 未找到 March7thAssistant: {M7_ROOT}")
            self.task_finished.emit(1)
            return False
        self._thread = _TaskThread(self.task_id, M7_ROOT, self)
        self._thread.start()
        self.task_started.emit()
        self.task_finished.emit(0) if False else None
        return True

    def stop(self):
        """请求停止：标记——m7 任务内部无检查点，单轮自然结束后退出。"""
        if self._thread is not None and self._thread.isRunning():
            self._stopped_by_user = True
            self._thread.request_stop()
            return True
        return False

    def poll(self):
        """主线程轮询：日志 + 结束状态（本环境 QThread 信号不投递——轮询兜底）。"""
        if self._thread is None:
            return
        for line in self._thread.drain_logs():
            self.log_line.emit(line)
        result = self._thread._result
        if result is None:
            return
        self._thread._result = None
        kind, payload = result
        if kind == "done":
            self.task_finished.emit(payload if isinstance(payload, int) else 0)
        else:
            self.log_line.emit(f"[错误] {payload}")
            self.task_finished.emit(1)
        self._thread = None
