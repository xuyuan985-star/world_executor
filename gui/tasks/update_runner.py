"""m7 更新子进程封装（QProcess：git pull + 依赖同步 + 日志管道）。

与 TaskProcess 同模式（本环境 QThread 信号不可靠——QProcess 事件驱动）。
无需管理员（m7 目录与 m7_venv 都在用户目录）。更新不可停止（幂等：
pull --ff-only 中断可重跑）。
"""
from pathlib import Path

from PySide6.QtCore import QProcess, QObject, Signal


class UpdateProcess(QObject):
    log_line = Signal(str)
    update_finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None

    @property
    def running(self):
        return self._proc is not None and self._proc.state() == QProcess.Running

    def start(self):
        if self.running:
            return False
        script = Path(__file__).resolve().parent / "m7_updater.py"
        py = Path(__file__).resolve().parent.parent.parent / "m7_venv" / "Scripts" / "python.exe"
        if not py.exists():
            py = Path(__file__).resolve().parent.parent.parent / ".venv" / "Scripts" / "python.exe"
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        proc.start(str(py), ["-u", str(script)])
        self._proc = proc
        return True

    def _on_stdout(self):
        data = bytes(self._proc.readAllStandardOutput())
        if not data:
            return
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = repr(data)
        for line in text.splitlines():
            if line.strip():
                self.log_line.emit(line)

    def _on_finished(self, code, _status):
        self.update_finished.emit(code)

    def _on_error(self, err):
        if err == QProcess.FailedToStart:
            self.log_line.emit("[更新] 启动失败（python 不可用）")
            self.update_finished.emit(1)
