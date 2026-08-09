from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # world_executor 根（AI 审计 B1）

from gui.pages.command_deck import CommandDeck
from gui.controllers.mission_controller import MissionController
from gui.safe import gui_safe
from gui.pages.placeholder import (KnowledgePage, ObservationPage, SettingsPage,
                                   StudioPage, WorldGraphPage)
from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition)

from gui.theme import apply_theme


class MainWindow(FluentWindow):
    event_received = Signal(object)

    def __init__(self, targets, event_bus, api, parent=None,
                 mission_controller=None):
        super().__init__(parent)
        apply_theme(QApplication.instance())
        # Bug 232：版本信息入标题（用户反馈可定位构建）
        import importlib.metadata as _md
        try:
            _ver = _md.version("world-executor")
        except Exception:
            _ver = "dev"
        self.setWindowTitle(f"世界执行器 v{_ver}")
        self.setMinimumSize(1180, 720)
        # 第 62 轮：业务封装注入（缺省内部构造，测试可传 Fake）
        self.mission_controller = mission_controller or MissionController(api)
        # DPI 修复：窗口几何保存/恢复（游戏切分辨率时不被放大/移出屏幕）
        self._user_geometry = None
        self._screen_dpi = None
        self._restore_geometry()
        self._watch_screen_changes()

        # 指挥台构造兜底（嫌疑 2）：炸则用空目标实例——窗口仍活着，不整个死亡
        try:
            self.command_deck = CommandDeck(targets or [])
        except Exception:
            import traceback
            traceback.print_exc()
            self.command_deck = CommandDeck([])
        # 页面构造异常隔离——单页失败不拖垮主窗口
        self.world_graph = self._safe_page(WorldGraphPage)
        self.observation = self._safe_page(ObservationPage)
        self.knowledge = self._safe_page(KnowledgePage)
        self.studio = self._safe_page(StudioPage)
        self.settings = self._safe_page(SettingsPage)

        for page, name in [
            (self.command_deck, "commandDeck"),
            (self.world_graph, "worldGraph"),
            (self.observation, "observation"),
            (self.knowledge, "knowledge"),
            (self.studio, "studio"),
            (self.settings, "settings"),
        ]:
            page.setObjectName(name)

        self.addSubInterface(self.command_deck, FluentIcon.ROBOT, "")
        self.addSubInterface(self.world_graph, FluentIcon.GLOBE, "")
        self.addSubInterface(self.observation, FluentIcon.HISTORY, "")
        self.addSubInterface(self.knowledge, FluentIcon.FOLDER, "")
        self.addSubInterface(self.studio, FluentIcon.APPLICATION, "")
        self.addSubInterface(self.settings, FluentIcon.SETTING, "",
                             position=NavigationItemPosition.BOTTOM)

        self.navigationInterface.setExpandWidth(56)
        self.navigationInterface.setCollapsible(False)

        title_bar = self.titleBar
        brand = QLabel("WORLD EXECUTOR")
        brand.setObjectName("brandLabel")
        sub = QLabel("黑塔空间站宝箱猎人")
        sub.setObjectName("brandSubLabel")
        title_bar.hBoxLayout.insertWidget(2, brand)
        title_bar.hBoxLayout.insertWidget(3, sub)

        self.event_bus = event_bus
        self.api = api
        self.event_bus.subscribe(self._on_runtime_event)
        # Bug 59：信号→GUI 线程槽（跨线程安全链）
        self.event_received.connect(self._on_event_delivered)
        self.command_deck.run_requested.connect(
            lambda targets: self._start_run(targets, self.command_deck.mode()))
        self.command_deck.stop_requested.connect(self._stop_run)

        from PySide6.QtCore import QThread, Signal

        class HealthWorker(QThread):
            done = Signal(dict, str)  # Bug 23：capability + 错误信息（不再吞异常）

            def run(self):
                # Bug 5：cwd 切换逻辑已移除——March7thVision 锁内构造并立即恢复
                # （线程安全由 runtime/drivers/march7th/vision.py 保证）
                from runtime.health import check_health
                self.done.emit(check_health().get("capability", {}), "")

        self._health_worker = HealthWorker(self)
        self.command_deck.set_health_status("正在检测环境...", busy=True)
        self._health_worker.done.connect(self._on_health_done)
        self._health_worker.start()

    def _safe_page(self, page_cls):
        """Bug 53：页面构造异常 → ErrorPage（显示错误，主窗口照常启动）。"""
        try:
            return page_cls()
        except Exception as e:
            import traceback
            traceback.print_exc()
            from gui.pages.placeholder import error_page
            return error_page(page_cls.__name__, str(e))

    def _on_health_done(self, health, error):
        # Bug 22/23：检测完成状态反馈（失败显示原因，不再静默）
        self._health = health or {}
        if error:
            self.command_deck.set_health_status("环境检测失败: " + error[:120], busy=False)
        else:
            self.command_deck.set_health(health)
            # 健康提示：关键项失败给可行动原因（非管理员/前台）
            hints = []
            if health.get("admin") is False:
                hints.append("输入被拦（非管理员）→ 请以管理员运行")
            if health.get("foreground") is False and health.get("window"):
                hints.append("游戏窗口不在前台 → 切回游戏窗口")
            if hints:
                self.command_deck.set_health_status("；".join(hints), busy=False)
            else:
                self.command_deck.set_health_status("环境就绪", busy=False)
            self._sync_runtime_state()

    def _sync_runtime_state(self):
        """Bug 102：状态恢复——GUI 启动/重开时主动同步 runtime（不只等事件）。"""
        st = getattr(self.mission_controller, "state", None)
        if st == "running":
            self.command_deck.led.setText("● 运行中（恢复同步）")
            self.command_deck.led.setStyleSheet("color: #4FD1C5; font-size: 12px;")
            self.command_deck.start_btn.setEnabled(False)
            self.command_deck.stop_btn.setEnabled(True)

    def _restore_geometry(self):
        """DPI 修复：启动时恢复用户上次窗口大小（QSettings）。"""
        try:
            from PySide6.QtCore import QSettings
            s = QSettings("WorldExecutor", "Studio")
            self.resize(int(s.value("win_w", 1280)), int(s.value("win_h", 760)))
        except Exception:
            pass

    def _save_geometry(self):
        try:
            from PySide6.QtCore import QSettings
            s = QSettings("WorldExecutor", "Studio")
            s.setValue("win_w", self.width())
            s.setValue("win_h", self.height())
        except Exception:
            pass

    def _watch_screen_changes(self):
        """DPI 修复：主屏几何/DPI 变化（游戏切分辨率）→ 恢复用户窗口大小。

        游戏全屏切换会使 Qt 重排布局导致窗口放大/移出屏幕。
        """
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self._screen_dpi = screen.logicalDotsPerInch()

        def _on_change():
            cur = screen.logicalDotsPerInch()
            changed = self._screen_dpi and abs(cur - self._screen_dpi) > 1
            self._screen_dpi = cur
            if changed:
                # 分辨率/DPI 切换 → 恢复用户窗口大小（居中在屏内）
                saved = (self.width(), self.height()) if not self._user_geometry \
                    else self._user_geometry
                if saved and saved != (0, 0):
                    self.resize(*saved)
                    self._user_geometry = saved
        try:
            screen.logicalDotsPerInchChanged.connect(_on_change)
            screen.geometryChanged.connect(_on_change)
        except Exception:
            pass

    def shutdown(self):
        """第 62 轮：统一关闭（controller/worker/订阅）。"""
        self._save_geometry()  # DPI 修复：退出保存窗口大小
        try:
            self.mission_controller.stop()
        except Exception:
            pass
        self._save_diag_snapshot()

    def _save_diag_snapshot(self):
        """Bug 187：退出现场保存（运行指标/线程/状态）——复盘"昨晚挂了"。"""
        import json
        import threading
        from pathlib import Path
        try:
            snap = {
                "api_state": getattr(self.mission_controller, "state", None),
                "threads": [t.name for t in threading.enumerate()
                            if t.is_alive() and t is not threading.current_thread()],
                "execution_id": getattr(getattr(self, "api", None),
                                       "execution_id", None),
            }
            log_dir = Path(__file__).resolve().parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "gui_snapshot.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def closeEvent(self, event):
        # Bug 7：关闭顺序——先停 worker/取消订阅（杜绝后台线程继续发 GUI 信号），
        # 再停 Runtime（防后台继续点击），最后保存诊断
        if getattr(self, "_health_worker", None) is not None and self._health_worker.isRunning():
            self._health_worker.quit()
            self._health_worker.wait(1000)
        # #57：窗口销毁时取消事件订阅（防已删 Qt 信号被后续 publish 调用）
        if getattr(self, "event_bus", None) is not None:
            self.event_bus.unsubscribe(self._on_runtime_event)
        self.shutdown()
        event.accept()

    @gui_safe
    def _start_run(self, targets, mode="dry"):
        # Bug 21：防重复启动（连点/事件未达窗口期）
        if self.mission_controller.state not in ("idle", "done", "crashed", "invalid"):
            return
        # 真机模式前置校验（G3 会拦，但提前告知更好）
        if mode == "real" and getattr(self, "_health", None):
            h = self._health
            warns = []
            if h.get("admin") is False:
                warns.append("非管理员（输入会被 UIPI 拦截）")
            if h.get("foreground") is False:
                warns.append("游戏窗口不在前台")
            if warns:
                self.command_deck.led.setText("● 真机执行需先处理: " + "；".join(warns))
                self.command_deck.led.setStyleSheet("color: #FFB454; font-size: 12px;")
                self.command_deck.start_btn.setEnabled(True)
                self.command_deck.stop_btn.setEnabled(False)
                return
        self.command_deck.reset()
        self.command_deck.set_starting()  # Bug 30：同步禁按钮（不依赖事件）
        try:
            # 第 62 轮：业务细节封装在 controller（路径/规格不再裸露在 GUI）
            self.mission_controller.start(targets, mode=mode)
        except Exception as e:
            # Bug 30：同步异常直接反馈（按钮不永久卡死）
            self.command_deck.led.setText("● 启动失败: " + str(e)[:100])
            self.command_deck.start_btn.setEnabled(True)
            self.command_deck.stop_btn.setEnabled(False)

    @gui_safe
    def _stop_run(self):
        self.command_deck.set_stopping()  # Bug 31：停止反馈先于结果
        self.mission_controller.stop()

    def _on_runtime_event(self, event):
        # Bug 59：runner 线程可能调用本方法——只 emit 信号（Qt 队列投递，
        # 跨线程安全），绝不在此直调 Qt 控件
        self.event_received.emit(event)

    @gui_safe
    def _on_event_delivered(self, event):
        # GUI 线程内执行（信号队列投递后）——所有 Qt 控件操作都在这里
        self.command_deck.on_event(event)
        # 观察中心同步接收事件统计
        if hasattr(self.observation, "on_event"):
            self.observation.on_event(event)
