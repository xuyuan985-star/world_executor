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


def _install_excepthook():
    """Bug 54：全局异常捕获——Qt 槽/线程异常落盘 + 提示（不静默）。"""
    import logging
    from pathlib import Path
    log_path = Path(__file__).resolve().parent.parent / "logs" / "gui_error.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Bug 294：日志轮转（10MB × 5 备份，防长期运行日志爆盘）
    from logging.handlers import RotatingFileHandler
    _h = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_h)
    logging.getLogger().setLevel(logging.ERROR)
    _orig = sys.excepthook

    def hook(t, v, tb):
        import traceback
        traceback.print_exception(t, v, tb)
        logging.error("uncaught", exc_info=(t, v, tb))
        try:
            from PySide6.QtWidgets import QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(None, "WorldExecutor 错误",
                                     f"发生未捕获异常:\n{t.__name__}: {v}")
        except Exception:
            pass
        _orig(t, v, tb)

    sys.excepthook = hook


def main():
    _install_excepthook()
    # Bug 150：单实例保护（QSharedMemory——自动化工具防双开冲突）
    from PySide6.QtCore import QSharedMemory
    single = QSharedMemory("WorldExecutorStudio_SingleInstance")
    if not single.create(1):
        from PySide6.QtWidgets import QMessageBox
        app_tmp = QApplication(sys.argv)
        QMessageBox.information(None, "WorldExecutor Studio",
                                "程序已在运行（单实例）")
        return
    import ctypes
    if sys.platform == "win32":  # AI 审计 B2：非 Windows 不调 windll
        ctypes.windll.user32.SetProcessDPIAware()  # #18：DPI context 进程早期设置
    if _elevate_if_needed():
        return  # 已发起提权，本进程退出
    app = QApplication(sys.argv)
    # DPI 修复：游戏启动切分辨率时防 Qt 缩放舍入放大（125% 不四舍五入成 150%）
    from PySide6.QtCore import Qt as _Qt
    app.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app.setApplicationName("WorldExecutor Studio")
    apply_theme(app)

    # 目标 = 攻略存档真实点位（非测试包假数据 chest_A/B/C/D）
    from knowledge.guides_loader import load_guide_targets, load_guide_regions
    targets = []
    try:  # 嫌疑 3：加载异常也走兜底（不只空列表）
        targets = load_guide_targets("02_herta_space_station", types=["chest"])
        regions = {r["id"]: r["name"] for r in load_guide_regions("02_herta_space_station")}
        # 目标附带区域中文名（指挥台展示用）+ 地图级分组
        for t in targets:
            t["room"] = regions.get(t["region"], t["region"])
            t["map_name"] = "黑塔空间站"
    except Exception:
        import traceback
        traceback.print_exc()
        targets = []
    if not targets:  # 攻略存档为空/异常时回退测试包（保持可运行）
        pkg = KnowledgePackage(ROOT / "knowledge/source/black_tower_test")
        targets = pkg.chests or []
    bus = EventBus(persist_path=str(ROOT / "ingest/raw/events/studio.jsonl"))
    api = RuntimeAPI(bus)
    window = MainWindow(targets, bus, api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
