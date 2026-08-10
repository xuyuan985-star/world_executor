"""m7 任务子进程封装（QProcess：启动/日志管道/停止/退出信号）。"""
import os
from pathlib import Path

from PySide6.QtCore import QProcess, QObject, Signal


class TaskProcess(QObject):
    """跑一个 m7 任务（python main.py <action>）。

    审查根因（本环境多轮实测）：QThread 跨线程信号不可靠——QProcess 是
    Qt 原生异步（事件驱动），stdout 信号在 GUI 线程投递，无此问题。
    """

    log_line = Signal(str)          # 一行输出（utf-8 解码，错误兜底）
    task_finished = Signal(int)     # 退出码（0=成功，负=被停止/异常）
    task_started = Signal()         # 进程成功启动

    def __init__(self, task_id, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._proc = None
        self._stopped_by_user = False

    @property
    def running(self):
        return self._proc is not None and self._proc.state() == QProcess.Running

    def start(self):
        from gui.tasks.catalog import M7_ROOT, M7_PYTHON

        if self.running:
            return False
        self._stopped_by_user = False
        # m7 main.py 顶层 pyuac 提权：非管理员会 UAC 弹窗提权重启新进程——
        # 提权后的进程脱离本 QProcess（日志断流、停止失效、"假成功"）。
        # fail-closed：非管理员直接拒绝启动（GUI 应经 bat RunAs 提权）。
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                self.log_line.emit(
                    "[错误] 任务需要管理员权限——请通过启动脚本以管理员运行本程序")
                self.task_finished.emit(1)
                return False
        except Exception:
            pass
        if not M7_ROOT.exists():
            self.log_line.emit(f"[错误] 未找到 March7thAssistant: {M7_ROOT}")
            self.task_finished.emit(1)
            return False
        if not (M7_ROOT / "main.py").exists():
            self.log_line.emit(f"[错误] March7thAssistant 缺 main.py: {M7_ROOT}")
            self.task_finished.emit(1)
            return False
        python = str(M7_PYTHON) if M7_PYTHON.exists() else "python"

        proc = QProcess(self)
        proc.setWorkingDirectory(str(M7_ROOT))
        env = QProcess.systemEnvironment()
        # 跳过 m7 first_run 检查（auto_update=false 会直接退出）与结束 pause
        env.append("MARCH7TH_DOCKER_STARTED=true")
        proc.setEnvironment(env)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        # 经 launcher 启动：注入 pylnk3 stub（m7 module/config 混入 payload，
        # 不注入则 import 崩）+ runpy 跑 main.py。
        # -u：QProcess 管道下 stdout 全缓冲——m7 logger 输出不 flush 就不出，
        # 实时日志会"消失"到缓冲满/退出（实测链路验证发现的坑）
        launcher = Path(__file__).resolve().parent / "m7_launcher.py"
        proc.start(python, ["-u", str(launcher), self.task_id])
        self._proc = proc
        self.task_started.emit()
        return True

    def stop(self):
        """停止任务：标记用户停止 → TerminateProcess（m7 任务幂等，中断安全）。"""
        if self._proc is not None and self.running:
            self._stopped_by_user = True
            self._proc.kill()
            return True
        return False

    def _on_stdout(self):
        data = bytes(self._proc.readAllStandardOutput())
        self._emit_text(data)

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError())
        self._emit_text(data)

    def _emit_text(self, data):
        if not data:
            return
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = repr(data)
        for line in text.splitlines():
            if line.strip():
                self.log_line.emit(line)

    def _on_finished(self, exit_code, _exit_status):
        if self._stopped_by_user:
            self.log_line.emit("[已停止]")
        self.task_finished.emit(exit_code)

    def _on_error(self, err):
        if err == QProcess.FailedToStart:
            self.log_line.emit(f"[错误] 任务进程启动失败（python/路径不可用）: "
                               f"{self.task_id}")
            self.task_finished.emit(1)
