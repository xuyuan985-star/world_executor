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

# Bug 13：单实例句柄进程级存活（模块顶层持有，防局部变量回收导致锁失效）
SINGLE_INSTANCE = None


def _elevate_if_needed():
    """BLOCKER-1：权限前置——启动即确认，不在运行途中临时弹 UAC。

    非管理员启动 GUI：询问一次（是 → runas 提权重启；否 → 低权限浏览模式，
    真机执行会被 G3 门槛 gate_blocked——health 已检 admin，绝不中途弹窗）。
    返回 True 表示已发起提权并应退出当前进程。
    """
    # Bug 12/31：非 Windows 平台不触碰 windll（先于任何 ctypes 调用）
    if sys.platform != "win32":
        return False
    import ctypes
    import sys as _sys
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    from PySide6.QtWidgets import QApplication, QMessageBox
    # Bug 32：弹窗需要 app——此处创建，main() 通过 instance() 复用（绝不二次创建）
    QApplication.instance() or QApplication(_sys.argv)
    box = QMessageBox()
    box.setWindowTitle("WorldExecutor Studio")
    box.setIcon(QMessageBox.Question)
    box.setText("当前不是管理员权限。\n真机执行（点击游戏窗口）需要管理员权限。")
    box.setInformativeText("选择「是」将重启并请求管理员权限；\n选择「否」以只读模式打开（可浏览，真机执行将被阻止）。")
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.Yes)
    if box.exec_() != QMessageBox.Yes:
        return False
    # Bug 30：提权启动失败（UAC 拒绝/系统错误）→ 明确提示，不静默退出
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", _sys.executable, " ".join(_sys.argv), None, 1)
    if result <= 32:
        QMessageBox.warning(None, "WorldExecutor Studio",
                            f"提权启动失败（错误码 {result}）。\n"
                            "可手动右键「以管理员身份运行」")
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
        # Bug 128：异常日志带运行上下文（当前任务/状态——崩溃可复盘）
        try:
            from gui.main_window import MainWindow
            ctx = ""
            for w in QApplication.instance().topLevelWidgets():
                if isinstance(w, MainWindow):
                    mc = getattr(w, "mission_controller", None)
                    if mc is not None:
                        ctx = (f"state={getattr(mc, 'state', '?')} "
                               f"knowledge={getattr(mc, 'knowledge_dir', '?')}")
                    break
            if ctx:
                logging.getLogger().error("runtime_context: %s", ctx)
        except Exception:
            pass
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
    """Bug 98：统一错误入口——任何启动异常 → 崩溃对话框（不静默/不闪退）。"""
    try:
        _start()
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None, "WorldExecutor 启动失败",
                f"启动过程中发生异常：\n{traceback.format_exc()[-800:]}")
        except Exception:
            pass
        sys.exit(1)


def _start():
    _install_excepthook()
    # Bug 13：单实例锁必须进程级存活（局部变量会被回收→锁失效）
    global SINGLE_INSTANCE
    # Bug 150：单实例保护（QSharedMemory——自动化工具防双开冲突）
    from PySide6.QtCore import QSharedMemory
    SINGLE_INSTANCE = QSharedMemory("WorldExecutorStudio_SingleInstance")
    if not SINGLE_INSTANCE.create(1):
        from PySide6.QtWidgets import QMessageBox
        app_tmp = QApplication(sys.argv)
        QMessageBox.information(None, "WorldExecutor Studio",
                                "程序已在运行（单实例）")
        return
    if _elevate_if_needed():
        return  # 已发起提权，本进程退出
    # Bug 32：复用提权检查阶段创建的 QApplication（Qt 只允许一个实例）
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    # DPI 修复：游戏启动切分辨率时防 Qt 缩放舍入放大（125% 不四舍五入成 150%）
    # Bug 14：不再手动 SetProcessDPIAware——Qt6 创建 QApplication 时统一接管
    #（进程级 DPI awareness 由 Qt 设置，mss/win32 截图运行时自动沿用）
    from PySide6.QtCore import Qt as _Qt
    app.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app.setApplicationName("WorldExecutor Studio")
    apply_theme(app)

    # 目标 = 攻略存档真实点位（非测试包假数据 chest_A/B/C/D）
    from knowledge.guides_loader import load_guide_targets, load_guide_regions
    # Bug 33：地图从设置读取（新增地图经设置即可接入 GUI）
    try:
        from config.settings import default_map
        map_id = default_map()
    except Exception:
        map_id = "02_herta_space_station"
    targets = []
    try:
        targets = load_guide_targets(map_id, types=["chest"])
        regions = {r["id"]: r["name"] for r in load_guide_regions(map_id)}
        # 目标附带区域中文名（指挥台展示用）+ 地图级分组
        for t in targets:
            t["room"] = regions.get(t["region"], t["region"])
            t["map_name"] = "黑塔空间站"
    except FileNotFoundError:
        # Bug 34：库不存在 = 环境问题（可提示继续浏览），非代码损坏
        print(f"[warn] 攻略库不存在（{map_id}）——指挥台将无目标可选")
    except Exception:
        # Bug 34：JSON 损坏/其他异常不再伪装成正常启动——暴露真实错误
        raise
    if not targets:
        print(f"[warn] 攻略库无目标（{map_id}）——指挥台将无目标可选")
    bus = EventBus(persist_path=str(ROOT / "ingest/raw/events/studio.jsonl"))
    api = RuntimeAPI(bus)
    window = MainWindow(targets, bus, api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
