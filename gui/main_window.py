from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # world_executor 根（AI 审计 B1）

from gui.pages.command_deck import CommandDeck
from gui.controllers.mission_controller import MissionController
from gui.safe import gui_safe


class HealthWorker(QThread):
    """Bug 623：模块级 HealthWorker（可测试/可复用——不再嵌套在 __init__ 内）。

    Bug 23：done 携带 capability + 错误信息（不再吞异常）。
    """

    done = Signal(dict, str)

    def run(self):
        # Bug 5：cwd 切换逻辑已移除——March7thVision 锁内构造并立即恢复
        # （线程安全由 runtime/drivers/march7th/vision.py 保证）
        try:
            from runtime.health import check_health
            result = check_health()
            # Bug 632：health 结果必须 dict（None/False → 明确错误，不静默卡界面）
            if not isinstance(result, dict):
                raise RuntimeError(f"check_health 返回非法类型: {type(result).__name__}")
            self.done.emit(result.get("capability", {}), "")
        except Exception:
            # Bug 633：完整 traceback 回传（GUI 可定位，非只 str(e)）
            import traceback
            self.done.emit({}, traceback.format_exc())
from gui.pages.placeholder import (KnowledgePage, ObservationPage, SettingsPage,
                                   StudioPage, WorldGraphPage)
from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition)

from gui.theme import apply_theme


class MainWindow(FluentWindow):
    event_received = Signal(object)

    def __init__(self, targets, event_bus, api, parent=None,
                 mission_controller=None):
        super().__init__(parent)
        # Bug 634：event_bus 必须非空（None 时所有订阅/事件驱动会崩）
        if event_bus is None:
            raise ValueError("MainWindow 需要 EventBus（测试请传 Fake 总线）")
        apply_theme(QApplication.instance())
        # Bug 232：版本信息入标题（用户反馈可定位构建）——Bug 194：单一版本源
        from config.version import APP_VERSION
        self.setWindowTitle(f"世界执行器 v{APP_VERSION}")
        # Bug 639：最小尺寸按屏幕可用区动态限制（小屏/DPI 缩放不溢出）
        try:
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                self.setMinimumSize(
                    min(1180, avail.width()), min(720, avail.height()))
            else:
                self.setMinimumSize(1180, 720)
        except Exception:
            self.setMinimumSize(1180, 720)
        # 第 62 轮：业务封装注入（缺省内部构造，测试可传 Fake）
        # Bug 15：知识目录显式注入——与 run.py 目标加载同源（真点位执行包，
        # 内含 30 条真点位模板 workflow；guides/maps 是展示库，无 workflow 不能执行）
        # Bug 635：is not None 判定（falsy 的 FakeController 不被误替换）
        self.mission_controller = mission_controller \
            if mission_controller is not None else MissionController(
                api, knowledge_dir=str(ROOT / "knowledge/source/black_tower_test"))
        # DPI 修复：窗口几何保存/恢复（游戏切分辨率时不被放大/移出屏幕）
        self._user_geometry = None
        self._screen_dpi = None
        self._restore_geometry()
        self._watch_screen_changes()

        # 指挥台构造兜底：失败走 error_page（不再二次创建失败对象——Bug 621）
        self.command_deck = self._safe_page(CommandDeck, targets or [])
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

        self._health_worker = HealthWorker(self)
        self.command_deck.set_health_status("正在检测环境...", busy=True)
        self._health_worker.done.connect(self._on_health_done)
        self._health_worker.start()
        # 系统状态实时刷新：每 5 秒重新检测（健康栏急速响应——
        # 游戏窗口出现/消失、前台变化、输入可用性变化都快速反映）。
        # 检测无副作用（L2 按键注入/前台激活已改为 gate 专用——此刷新安全）
        from PySide6.QtCore import QTimer
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5000)
        self._health_timer.timeout.connect(self._refresh_health)
        self._health_timer.start()
        # Bug 257：监听 IPC 唤醒（第二实例激活本窗口）
        # BUG-010：不无条件 removeServer（会删掉并发实例刚建的 server）——
        # 仅 listen 失败（残留）时才清理重试一次
        self._wake_server = None
        try:
            from PySide6.QtNetwork import QLocalServer
            server = QLocalServer(self)
            if not server.listen("WorldExecutorStudio_Wake"):
                QLocalServer.removeServer("WorldExecutorStudio_Wake")
                if not server.listen("WorldExecutorStudio_Wake"):
                    raise RuntimeError("QLocalServer listen 失败（二次）")
            server.newConnection.connect(self._on_wake_request)
            self._wake_server = server
        except Exception:
            # P0-001：IPC 唤醒监听失败不静默（可选功能，但需可查）
            import logging
            logging.getLogger("gui.main_window").exception(
                "IPC 唤醒监听启动失败")
            self._wake_server = None

    def _on_wake_request(self):
        # Bug 257：收到第二实例 activate 消息 → 置顶显示
        # Bug 523：IPC 消息格式校验——只接受精确 "activate"（防非法/损坏消息）
        try:
            conn = self._wake_server.nextPendingConnection()
            if conn is None:
                return
            raw = bytes(conn.readAll()).decode("utf-8", errors="ignore")
            conn.disconnectFromServer()
            if raw.strip() != "activate":
                import logging
                logging.getLogger("gui.main_window").warning(
                    "非法 IPC 消息: %r", raw[:60])
                return
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception:
            # P0-001：唤醒处理异常不静默
            import logging
            logging.getLogger("gui.main_window").exception(
                "IPC 唤醒处理失败")

    def start_foreground_watch(self, interval_ms=3000):
        """持续前台守护：定时检测游戏窗口是否在前台，不在则自动拉置顶。"""
        from PySide6.QtCore import QTimer
        if getattr(self, "_fg_watch", None) is not None:
            return
        self._fg_watch = QTimer(self)
        self._fg_watch.setInterval(interval_ms)
        self._fg_watch.timeout.connect(self._ensure_game_foreground)
        self._fg_watch.start()
        # 同时开启 HUD（对齐 M7：游戏窗口左下角日志层）
        self._start_hud()

    def _start_hud(self):
        """F10 全局热键 + 游戏窗口 HUD 日志层（对齐 M7）。"""
        try:
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return
            # F10 全局热键：keyboard 库（M7 同款——RegisterHotKey 在此环境不可靠）
            from gui.hotkey import GlobalHotkey
            self._hotkeys = GlobalHotkey(self)
            self._hotkeys.pressed.connect(self._on_hotkey)
            self._hotkeys.register("f10", None)
            # HUD
            from gui.overlay import GameHudController
            self._hud = GameHudController(self.event_bus, game["hwnd"])
            self._hud.show()
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("HUD/热键启动失败")

    def _on_hotkey(self, key):
        # keyboard 回调线程 → 信号 → 主线程
        if key == "f10":
            self._emergency_hotkey()

    def _emergency_hotkey(self):
        """F10：紧急停止——释放全部按键 + 停止任务 + HUD 提示。"""
        import logging
        logging.getLogger("gui.main_window").warning("F10 紧急停止触发")
        try:
            # 释放可能卡住的按键
            mc = self.mission_controller
            if mc is not None:
                mc.stop()
        except Exception:
            pass
        try:
            import ctypes
            # 兜底：释放 W/A/S/D/Esc/空格 的 keyup
            for vk in (0x57, 0x41, 0x53, 0x44, 0x1B, 0x20):
                ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)
        except Exception:
            pass
        if getattr(self, "_hud", None) is not None:
            self._hud.overlay.set_emergency()
        self.command_deck.led.setText("⚠ F10 紧急停止（按键已释放）")
        self.command_deck.led.setStyleSheet("color: #E64545; font-size: 12px;")

    def _refresh_health(self):
        """系统状态周期刷新：检测进行中跳过（防重入），完成后回调更新。"""
        if self._health_worker.isRunning():
            return
        self._health_worker.start()

    def _ensure_game_foreground(self):
        """检测游戏前台——不在则自动激活（用户要求：开始后持续拉置顶）。"""
        try:
            import ctypes
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return  # 游戏没开——不打扰
            fg = ctypes.windll.user32.GetForegroundWindow()
            if fg != game["hwnd"]:
                from runtime.win_capture import set_foreground_with_retry
                set_foreground_with_retry(game["hwnd"])
            # HUD 跟随窗口位置
            hud = getattr(self, "_hud", None)
            if hud is not None and hud.overlay.isVisible():
                hud.reposition()
        except Exception:
            pass

    def _safe_page(self, page_cls, *args):
        """Bug 53：页面构造异常 → ErrorPage（显示错误，主窗口照常启动）。
        Bug 621：只尝试一次——失败显示错误页，不重复创建失败对象。"""
        try:
            return page_cls(*args)
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
        # BUG-012：状态可能为 str 或 Enum——统一取 value 比较（类型安全）
        if getattr(st, "value", st) == "running":
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
            import logging
            logging.getLogger("gui.main_window").warning("窗口几何恢复失败")

    def _save_geometry(self):
        try:
            from PySide6.QtCore import QSettings
            s = QSettings("WorldExecutor", "Studio")
            s.setValue("win_w", self.width())
            s.setValue("win_h", self.height())
        except Exception:
            import logging
            logging.getLogger("gui.main_window").warning("窗口几何保存失败")

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
            import logging
            logging.getLogger("gui.main_window").warning("屏幕变化监听注册失败")

    def shutdown(self):
        """第 62 轮：统一关闭（controller/worker/订阅）。"""
        self._save_geometry()  # DPI 修复：退出保存窗口大小
        try:
            self.mission_controller.stop()
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("停止 MissionController 失败")
        # 审查：事件文件句柄关闭（bus.close 原无调用方）
        try:
            if getattr(self, "event_bus", None) is not None:
                self.event_bus.close()
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
            import logging
            logging.getLogger("gui.main_window").warning("退出现场保存失败")

    def closeEvent(self, event):
        # Bug 7：关闭顺序——先停 worker/取消订阅（杜绝后台线程继续发 GUI 信号），
        # 再停 Runtime（防后台继续点击），最后保存诊断
        # BUG-009：wait 超时（check_health 内部阻塞）→ 明确警告而非静默残留
        if getattr(self, "_health_worker", None) is not None and self._health_worker.isRunning():
            self._health_worker.requestInterruption()
            if not self._health_worker.wait(3000):
                import logging
                logging.getLogger("gui.main_window").warning(
                    "HealthWorker 关闭超时（线程可能残留）")
        # #57：窗口销毁时取消事件订阅（防已删 Qt 信号被后续 publish 调用）
        # BUG-011：取消订阅异常不阻断关闭链（各步隔离）
        try:
            if getattr(self, "event_bus", None) is not None:
                self.event_bus.unsubscribe(self._on_runtime_event)
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("取消事件订阅失败")
        self.shutdown()
        event.accept()

    @gui_safe
    def _start_run(self, targets, mode="dry"):
        # Bug 21：防重复启动（连点/事件未达窗口期）
        # 审查 P0-6：stopped（手动停止）/gate_blocked（G3 拦截）也可重启——
        # 原集合缺这两态导致停止后按钮恢复但点击永久静默
        if self.mission_controller.state not in (
                "idle", "done", "crashed", "invalid",
                "stopped", "gate_blocked"):
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
        # 前台守护：开始任务即持续拉游戏置顶（用户要求）
        self.start_foreground_watch()
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
        # Bug 129：节流——事件入队，50ms 合并刷新（防 runtime 高频 emit 卡 GUI）
        self.event_received.emit(event)

    @gui_safe
    def _on_event_delivered(self, event):
        # Bug 129：合并处理——高频事件（observation/state_changed 流）批量刷新
        if not hasattr(self, "_pending_events"):
            self._pending_events = []
            from PySide6.QtCore import QTimer
            self._flush_timer = QTimer(self)
            self._flush_timer.setInterval(50)
            self._flush_timer.setSingleShot(True)
            self._flush_timer.timeout.connect(self._flush_events)
        self._pending_events.append(event)
        self._flush_timer.start()

    def _flush_events(self):
        # GUI 线程内执行（信号队列投递后）——所有 Qt 控件操作都在这里
        pending = getattr(self, "_pending_events", [])
        self._pending_events = []
        for event in pending:
            self.command_deck.on_event(event)
            # 观察中心同步接收事件统计
            if hasattr(self.observation, "on_event"):
                self.observation.on_event(event)
            # 审查 P1：完成状态持久化接线——目标 done 时记录（原实现是死代码）
            if event.type == "target_progress" \
                    and event.context.get("status") == "done" \
                    and event.context.get("target"):
                try:
                    self.mission_controller.record_completed(
                        [event.context["target"]])
                except Exception:
                    import logging
                    logging.getLogger("gui.main_window").exception(
                        "完成状态持久化失败")
            # 任务结束/报错 → HUD 收起（不再卡在游戏窗口）
            if event.type in ("run_finished", "pause_requested") \
                    and getattr(self, "_hud", None) is not None:
                try:
                    self._hud.hide()
                except Exception:
                    pass
