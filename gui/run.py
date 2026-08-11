import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# DPI 警告修复：RoundPreferFloor 必须在任何 QGuiApplication 创建前设置
#（此前在 app 创建后才调用——Qt 警告且不生效）
# 注意：这是 QGuiApplication 的静态方法（不是 Qt 类方法）
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt as _Qt
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    _Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import apply_theme
from runtime.api.commands import RuntimeAPI
from runtime.events.bus import EventBus

# Bug 13：单实例句柄进程级存活（模块顶层持有，防局部变量回收导致锁失效）
SINGLE_INSTANCE = None


def _elevate_if_needed():
    """提权前置——自动无感提权（不再弹询问框）。

    非管理员 → runas 自动提权重启（UAC 直接提升，本机无确认框）；
    提权失败（UAC 拒绝等）→ 以普通浏览模式继续（不阻断启动）。
    返回 True 表示已发起提权并应退出当前进程。
    """
    # Bug 12/31：非 Windows 平台不触碰 windll（先于任何 ctypes 调用）
    if sys.platform != "win32":
        return False
    # --no-elevate：显式浏览模式（跳过自动提权）
    if "--no-elevate" in sys.argv:
        return False
    import ctypes
    import os
    import sys as _sys
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    # 自动提权：lpDirectory 必须传当前工作目录（否则新进程 cwd=System32，
    # `python -m app` No module named 闪退——此前已修）
    # 审查 P0-5：argv 拼接必须引号（argv[0] 是含空格路径——不引号会被
    # ShellExecuteW 按空格截断成无效命令，elevate_trace 实证 result=42 但进程未启动）
    import os
    quoted = " ".join(f'"{a}"' if " " in a else a for a in _sys.argv)
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", _sys.executable, quoted,
        os.getcwd(), 1)
    try:  # 提权链路探针（排查"新进程没起来"）
        with open(ROOT / "logs" / "elevate_trace.log", "a", encoding="utf-8") as f:
            import time as _t
            f.write(f"{_t.strftime('%H:%M:%S')} pid={os.getpid()} "
                    f"exe={_sys.executable} args={_sys.argv} "
                    f"cwd={os.getcwd()} result={result}\n")
    except Exception:
        pass
    if result > 32:
        return True  # 提权启动成功 → 本进程退出，新进程接管
    # 提权失败（UAC 拒绝/错误）→ 普通模式继续（浏览可用，真机被 G3 拦）
    import logging
    logging.getLogger("gui.run").warning(
        "自动提权失败（错误码 %s）——以浏览模式启动", result)
    return False


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
    # Bug 112：日志脱敏（API key/cookie 不落盘）
    from config.settings import install_log_redaction
    install_log_redaction()
    # 崩溃排查：ERROR → INFO（m7 任务日志/退出路径可查，不再只记错误）
    logging.getLogger().setLevel(logging.INFO)
    # Bug 193：依赖缺失给安装指引（ModuleNotFoundError 不裸抛）
    _PIP_HINTS = {
        "PySide6": "pip install PySide6",
        "qfluentwidgets": "pip install PySide6-Fluent-Widgets",
        "PIL": "pip install pillow",
        "cv2": "pip install opencv-python",
        "mss": "pip install mss",
        "requests": "pip install requests",
        "ruamel": "pip install ruamel.yaml",
        "pyuac": "pip install pyuac",
        "win32gui": "pip install pywin32",
    }
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
        # Bug 197：崩溃现场自动保存（dump/state.json + 截图 + 日志）
        try:
            _save_crash_dump(t, v, tb)
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QMessageBox
            app = QApplication.instance()
            if app is not None:
                msg = f"发生未捕获异常:\n{t.__name__}: {v}"
                if isinstance(v, ModuleNotFoundError):
                    name = str(v).split("'")[1] if "'" in str(v) else ""
                    hint = _PIP_HINTS.get(name)
                    if hint:
                        msg += f"\n\n缺少依赖 {name} → {hint}"
                QMessageBox.critical(None, "WorldExecutor 错误", msg)
        except Exception:
            pass
        _orig(t, v, tb)

    sys.excepthook = hook


def _save_crash_dump(t, v, tb):
    """Bug 197：崩溃现场（dump/时间戳/state.json + 游戏截图 + 错误日志）。"""
    import time
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    dump_dir = root / "dump" / time.strftime("%Y%m%d_%H%M%S")
    dump_dir.mkdir(parents=True, exist_ok=True)
    import traceback as _tb
    (dump_dir / "traceback.txt").write_text(
        "".join(_tb.format_exception(t, v, tb)), encoding="utf-8")
    state = {}
    try:
        from gui.main_window import MainWindow
        for w in QApplication.instance().topLevelWidgets():
            if isinstance(w, MainWindow):
                mc = getattr(w, "mission_controller", None)
                state = {"state": getattr(mc, "state", None),
                         "knowledge_dir": getattr(mc, "knowledge_dir", None)}
                break
    except Exception:
        pass
    import json
    (dump_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 游戏画面现场
        from runtime.drivers.march7th.window import find_game_window
        from runtime.win_capture import capture_game_foreground
        game = find_game_window()
        if game:
            img = capture_game_foreground(game)
            img.save(dump_dir / "screen.png")
    except Exception:
        pass
    print(f"[crash] 现场已保存: {dump_dir}")


def main():
    """Bug 98：统一错误入口——任何启动异常 → 崩溃对话框（不静默/不闪退）。"""
    try:
        _start()
    except Exception:
        import traceback
        traceback.print_exc()
        # 启动失败必须落盘（pythonw 无控制台——弹窗之外日志可查）
        try:
            import datetime
            from pathlib import Path
            err_log = ROOT / "logs" / "startup_error.log"
            err_log.parent.mkdir(parents=True, exist_ok=True)
            with open(err_log, "a", encoding="utf-8") as f:
                f.write("\n===== " + datetime.datetime.now().isoformat()
                        + " =====\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
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
    # Bug 255：系统对象锁（崩溃自动释放，无锁文件残留）
    from PySide6.QtCore import QSharedMemory
    import time
    SINGLE_INSTANCE = QSharedMemory("WorldExecutorStudio_SingleInstance")
    if not SINGLE_INSTANCE.create(1):
        # 提权重启竞态修复：旧进程点「是」后还没退出（仍持锁），
        # 新进程此时 create 失败——等待重试（等旧进程释放锁），
        # 避免"点完是又消失"（新进程被误判为第二实例退出）
        acquired = False
        for _ in range(15):  # 最多等 4.5 秒
            time.sleep(0.3)
            if SINGLE_INSTANCE.create(1):
                acquired = True
                break
        if not acquired:
            # Bug 257：第二次启动 → IPC 唤醒旧窗口（不只干提示）
            try:
                from PySide6.QtNetwork import QLocalSocket
                sock = QLocalSocket()
                sock.connectToServer("WorldExecutorStudio_Wake")
                if sock.waitForConnected(500):
                    sock.write(b"activate")
                    sock.flush()
                    sock.waitForBytesWritten(500)
                    sock.disconnectFromServer()
            except Exception:
                pass
            from PySide6.QtWidgets import QMessageBox
            app_tmp = QApplication(sys.argv)
            QMessageBox.information(None, "WorldExecutor Studio",
                                    "程序已在运行（已尝试唤醒原窗口）")
            return
    if _elevate_if_needed():
        return  # 已发起提权，本进程退出
    # Bug 32：复用提权检查阶段创建的 QApplication（Qt 只允许一个实例）
    # 注意：QApplication 用模块级导入（函数内 import 会使其成局部变量，
    # 单实例分支第 227 行提前引用 → UnboundLocalError）
    app = QApplication.instance() or QApplication(sys.argv)
    # DPI：RoundPreferFloor 已在模块导入时设置（早于任何 QApplication 创建——
    # 此处不再重复调用，Qt 警告消除）
    app.setApplicationName("WorldExecutor Studio")
    apply_theme(app)
    # 根治窗口消失（WER 系列排查）：lastWindowClosed 误触发（HUD/工具窗口
    # 显示后 Qt 内部报最后窗口关闭）→ 自动 quit → 窗口消失。改为显式接管：
    # 只有 closeEvent 走完正常流程才 quit，任何 lastWindowClosed 不再自动退出。
    app.setQuitOnLastWindowClosed(False)

    # 目标 = 攻略存档真实点位（非测试包假数据 chest_A/B/C/D）
    from knowledge.guides_loader import (load_guide_targets,
                                         load_guide_regions,
                                         sync_custom_map)
    # 同步自定义地图（录制轨迹 → 08_custom 点位，与世界图/指挥台平级）
    # 第 9 轮：启动带当前启用集——无参会把用户取消勾选的轨迹全量启用
    # （勾选状态跨重启丢失）
    try:
        from knowledge.guides_loader import custom_enabled_names
        # 第 10 轮：空启用集（首次启动无 chests.json）→ None 全量启用——
        # 否则 set() 会把全部轨迹过滤成空，首次启动自定义轨迹全隐藏
        enabled = custom_enabled_names()
        sync_custom_map(enabled or None)
    except Exception as e:
        print(f"[warn] 自定义地图同步失败: {e}")
    # 加载全部地图目标（指挥台按地图分组显示——不再只加载默认图）
    # Bug 33 扩展：地图从设置读取（default_map 仅作默认启动图）
    targets = []
    maps_dir = ROOT / "knowledge/guides/maps"
    if maps_dir.is_dir():
        for md in sorted(maps_dir.iterdir()):
            if not md.is_dir():
                continue
            map_id = md.name
            # 地图显示名从攻略库 map.json 读（原硬编码"黑塔空间站"——
            # 换地图后指挥台分组名错误）
            map_display_name = map_id
            try:
                _md = json.loads((md / "map.json").read_text(encoding="utf-8"))
                map_display_name = _md.get("name") or map_id
            except Exception:
                pass
            try:
                ts = load_guide_targets(map_id, types=["chest"])
                regions = {r["id"]: r["name"]
                           for r in load_guide_regions(map_id)}
                # 目标附带区域中文名（指挥台展示用）+ 地图级分组
                for t in ts:
                    t["room"] = regions.get(t["region"], t["region"])
                    t["map_name"] = map_display_name
                targets.extend(ts)
            except FileNotFoundError:
                # Bug 34：库不存在 = 环境问题（可提示继续浏览），非代码损坏
                print(f"[warn] 攻略库不存在（{map_id}）——跳过该地图")
            except Exception:
                # Bug 34：JSON 损坏/其他异常不再伪装成正常启动——暴露真实错误
                raise
    if not targets:
        print("[warn] 攻略库无任何目标——指挥台将无目标可选")
    bus = EventBus(persist_path=str(ROOT / "ingest/raw/events/studio.jsonl"))
    api = RuntimeAPI(bus)
    window = MainWindow(targets, bus, api)
    window.show()
    # 退出路径探针：aboutToQuit（正常 quit / 最后窗口关闭）vs os._exit（跳过）
    try:
        import time as _time

        def _on_about_to_quit():
            # 关键：dump 全部线程栈——aboutToQuit 触发瞬间谁在干什么
            try:
                import faulthandler
                with open(ROOT / "logs" / "crash_trace.log", "a",
                          encoding="utf-8") as _f:
                    _f.write(f"\n===== aboutToQuit "
                             f"{_time.strftime('%Y-%m-%d %H:%M:%S')} "
                             f"all thread stacks =====\n")
                    faulthandler.dump_traceback(all_threads=True, file=_f)
            except Exception:
                pass
            _trace_exit(f"aboutToQuit fired (quitOnLastWindowClosed="
                        f"{app.quitOnLastWindowClosed()})")
            # 退出保护（0xC0000409 根因）：aboutToQuit 是 Qt 析构 QObject 树
            # 前的最后必经点——任何 quit 路径（lastWindowClosed/显式 quit/
            # 异常退出）都会先触发它。此时若有 QThread 仍在运行（m7 任务
            # 线程/HealthWorker），后续析构必崩（WER 多次实锤：崩在
            # app.exec() 返回前，exec 后保护来不及）。os._exit 跳过析构。
            # 注意：只查模块级注册表（创建即注册）——topLevelWidgets 遍历
            # 在窗口销毁中不可靠（可能抛异常），绝不依赖。
            _alive = []
            try:
                from gui.tasks.runner import all_running_qthreads
                _alive = list(all_running_qthreads())
            except Exception as _e:
                try:
                    _trace_exit(f"aboutToQuit guard: qthread check EXC {_e!r}")
                except Exception:
                    pass
            if _alive:
                _trace_exit(
                    f"aboutToQuit guard: {len(_alive)} QThread(s) running "
                    f"→ os._exit(0)（跳过 Qt 析构，防 0xC0000409）")
                import os as _os
                _os._exit(0)

        app.aboutToQuit.connect(_on_about_to_quit)
        # MainWindow C++ 对象销毁探针（非 closeEvent 路径的窗口消失）
        def _on_window_destroyed():
            import traceback as _tb
            try:
                with open(ROOT / "logs" / "exit_trace.log", "a",
                          encoding="utf-8") as _f:
                    _f.write(f"\n===== MainWindow C++ object DESTROYED "
                             f"{_time.strftime('%H:%M:%S')} — destroy stack =====\n")
                    _tb.print_stack(file=_f)
            except Exception:
                pass
            _trace_exit("MainWindow C++ object DESTROYED")
            # 兜底：窗口被销毁（非 closeEvent 路径）时若任务线程在跑，
            # Qt 析构子对象树必 0xC0000409——os._exit 跳过析构
            try:
                from gui.tasks.runner import all_running_qthreads
                if all_running_qthreads():
                    _trace_exit(
                        "destroyed guard: QThread(s) running → os._exit(0)")
                    import os as _os
                    _os._exit(0)
            except Exception:
                pass

        window.destroyed.connect(_on_window_destroyed)
    except Exception:
        pass
    rc = app.exec()
    _trace_exit(f"app.exec() returned rc={rc}")
    # 退出保护（0xC0000409）：app.exec() 返回后 Qt 将析构 QObject 树——
    # 若 HealthWorker 等 QThread 仍在运行，析构运行中 QThread → Qt6Core
    # qFatal 0xC0000409。兜底：跳过 Qt 析构直接 os._exit(0)。
    # 子进程模式（0.6.0）：m7 任务在独立 QProcess，不在此列。
    try:
        from gui.tasks.runner import all_running_qthreads
        alive = all_running_qthreads()
        if alive:
            _trace_exit(f"exit guard: {len(alive)} QThread(s) still running "
                        f"→ os._exit(0)（跳过 Qt 析构，防 0xC0000409）")
            import os as _os
            _os._exit(0)
    except Exception:
        pass
    sys.exit(rc)


def _trace_exit(msg):
    """退出探针——直接文件写（不依赖 logging level 配置）。"""
    try:
        import time as _time
        from pathlib import Path as _P
        p = _P(__file__).resolve().parent.parent / "logs" / "exit_trace.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
