import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import apply_theme
from runtime.api.commands import RuntimeAPI
from runtime.events.bus import EventBus
from runtime.knowledge_loader import KnowledgePackage


def _elevate_if_needed():
    """BLOCKER-1：权限前置——启动即确认，不在运行途中临时弹 UAC。

    非管理员启动 GUI：询问一次（是 → runas 提权重启；否 → 低权限浏览模式，
    真机执行会被 G3 门槛 gate_blocked——health 已检 admin，绝不中途弹窗）。
    返回 True 表示已发起提权并应退出当前进程。
    """
    import ctypes
    import sys as _sys
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    from PySide6.QtWidgets import QApplication, QMessageBox
    _app = QApplication.instance() or QApplication(_sys.argv)
    box = QMessageBox()
    box.setWindowTitle("WorldExecutor Studio")
    box.setIcon(QMessageBox.Question)
    box.setText("当前不是管理员权限。\n真机执行（点击游戏窗口）需要管理员权限。")
    box.setInformativeText("选择「是」将重启并请求管理员权限；\n选择「否」以只读模式打开（可浏览，真机执行将被阻止）。")
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.Yes)
    if box.exec_() != QMessageBox.Yes:
        return False
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", _sys.executable, " ".join(_sys.argv), None, 1)
    return True


def main():
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()  # #18：DPI context 进程早期设置
    if _elevate_if_needed():
        return  # 已发起提权，本进程退出
    app = QApplication(sys.argv)
    app.setApplicationName("WorldExecutor Studio")
    apply_theme(app)

    pkg = KnowledgePackage(ROOT / "knowledge/source/black_tower_test")
    targets = pkg.chests or []
    bus = EventBus(persist_path=str(ROOT / "ingest/raw/events/studio.jsonl"))
    api = RuntimeAPI(bus)
    window = MainWindow(targets, bus, api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
