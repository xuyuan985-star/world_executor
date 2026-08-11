from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QLabel

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # world_executor 根（AI 审计 B1）

from gui.pages.command_deck import CommandDeck
from gui.controllers.mission_controller import MissionController
from gui.safe import gui_safe


class HealthWorker(QThread):
    """模块级 HealthWorker（可测试/可复用——不再嵌套在 __init__ 内）。

    Bug 23：done 携带 capability + 错误信息（不再吞异常）。
    审查根因：本环境 PySide6 QThread 跨线程信号 → QObject 槽不投递
    （实测 dict/str/QPixmap 均失效）——结果改写入 self._result，
    由主线程定时轮询消费（见 MainWindow._poll_health）。
    """

    done = Signal(dict, str)

    def run(self):
        try:
            from runtime.health import check_health
            result = check_health()
            # Bug 632：health 结果必须 dict（None/False → 明确错误，不静默卡界面）
            if not isinstance(result, dict):
                raise RuntimeError(f"check_health 返回非法类型: {type(result).__name__}")
            self._result = (result.get("capability", {}), "")
        except Exception:
            # Bug 633：完整 traceback 回传（GUI 可定位，非只 str(e)）
            import traceback
            self._result = ({}, traceback.format_exc())
from gui.pages.placeholder import (KnowledgePage, ObservationPage, SettingsPage,
                                   TaskCenterPage, WorldGraphPage)
from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition)

from gui.theme import apply_theme


class MainWindow(FluentWindow):
    event_received = Signal(object)  # 保留（外部/测试兼容）——内部走轮询队列

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
        # 目标数据存档（录制同步后指挥台刷新用）
        self._all_targets = list(targets or [])

        # 指挥台构造兜底：失败走 error_page（不再二次创建失败对象——Bug 621）
        self.command_deck = self._safe_page(CommandDeck, targets or [])
        # 页面构造异常隔离——单页失败不拖垮主窗口
        self.world_graph = self._safe_page(WorldGraphPage)
        # 攻略体系"执行此区域"→ 知识包匹配 → 指挥台执行（接线）
        try:
            view = self.world_graph._view if hasattr(
                self.world_graph, "_view") else None
            if view is not None and hasattr(view, "run_requested"):
                view.run_requested.connect(self._on_guide_run)
        except Exception:
            pass
        self.observation = self._safe_page(ObservationPage)
        self.knowledge = self._safe_page(KnowledgePage)
        self.studio = self._safe_page(TaskCenterPage)
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

        for page, icon, nav_name, pos in [
            (self.command_deck, FluentIcon.ROBOT, "指挥台",
             NavigationItemPosition.TOP),
            (self.world_graph, FluentIcon.GLOBE, "世界图",
             NavigationItemPosition.TOP),
            (self.observation, FluentIcon.HISTORY, "观察中心",
             NavigationItemPosition.TOP),
            (self.knowledge, FluentIcon.FOLDER, "知识体系",
             NavigationItemPosition.TOP),
            (self.studio, FluentIcon.APPLICATION, "任务中心",
             NavigationItemPosition.TOP),
            (self.settings, FluentIcon.SETTING, "设置",
             NavigationItemPosition.BOTTOM),
        ]:
            item = self.addSubInterface(page, icon, "", position=pos)
            try:
                item.setToolTip(nav_name)  # 56px 纯图标条——tooltip 补文字
            except Exception:
                pass

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
        # 主事件链轮询（本环境跨线程 Qt 信号不可靠）——runner 线程只入队，
        # 主线程 QTimer 消费（见 _poll_runtime_events）。deque：append/popleft
        # 原子（审查：list 整体替换在并发下丢事件）
        from collections import deque as _deque
        self._runtime_queue = _deque()
        self._event_poll = QTimer(self)
        self._event_poll.setInterval(50)
        self._event_poll.timeout.connect(self._poll_runtime_events)
        self._event_poll.start()
        _deck = self._deck()
        if _deck is not None:
            _deck.run_requested.connect(
                lambda targets: self._start_run(targets))
            _deck.stop_requested.connect(self._stop_run)

        self._health_worker = HealthWorker(self)
        # 退出保护注册：HealthWorker 也是 QThread——aboutToQuit 时若仍在跑
        # （check_health 含 OCR 模型加载 1-2s），Qt 析构必崩。创建即注册，
        # guard 只查注册表（topLevelWidgets 遍历在窗口销毁中不可靠）。
        try:
            from gui.tasks.runner import register_qthread, unregister_qthread
            register_qthread(self._health_worker)
            self._health_worker.finished.connect(
                lambda: unregister_qthread(self._health_worker))
        except Exception:
            pass
        if _deck is not None:
            _deck.set_health_status("正在检测环境...", busy=True)
        # 审查根因：本环境 QThread 信号 → QObject 槽不投递——结果经
        # self._result 属性 + 主线程轮询消费（_poll_health）
        self._health_worker.start()
        # 结果消费轮询（500ms）+ 系统状态周期刷新（5s 重新检测）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_health)
        self._poll_timer.start()
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
        """持续前台守护：定时检测游戏窗口是否在前台，不在则自动拉置顶。

        任务运行期间启用；任务失败/停止/结束时必须 stop_foreground_watch
        停掉——否则失败后仍疯狂抢前台（0.6.0 排查修复）。
        """
        if getattr(self, "_fg_watch", None) is not None:
            return
        self._fg_watch = QTimer(self)
        self._fg_watch.setInterval(interval_ms)
        self._fg_watch.timeout.connect(self._ensure_game_foreground)
        self._fg_watch.start()
        # 同时开启 HUD（对齐 M7：游戏窗口左下角日志层）
        self._start_hud()

    def stop_foreground_watch(self):
        """停止前台守护（任务失败/停止/结束时调用——防失败后疯狂拉置顶）。"""
        fw = getattr(self, "_fg_watch", None)
        if fw is not None:
            try:
                fw.stop()
            except Exception:
                pass
            self._fg_watch = None

    def ensure_hud(self):
        """HUD 控制器（无则创建）——任务中心子进程任务复用同一 HUD。

        返回 GameHudController 或 None（游戏窗口不存在时）。"""
        try:
            if getattr(self, "_hud", None) is not None:
                return self._hud
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return None
            from gui.hotkey import GlobalHotkey
            if getattr(self, "_hotkeys", None) is None:
                self._hotkeys = GlobalHotkey(self)
                self._hotkeys.pressed.connect(self._on_hotkey)
                self._hotkeys.register("f10", None)
            from gui.overlay import GameHudController
            self._hud = GameHudController(self.event_bus, game["hwnd"])
            self._hud.show()
            return self._hud
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("ensure_hud 失败")
            return None

    def _start_hud(self):
        """F10 全局热键 + 游戏窗口 HUD 日志层（对齐 M7）。"""
        try:
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return
            # F10 全局热键：keyboard 库（M7 同款——RegisterHotKey 在此环境不可靠）
            # 审查：热键只注册一次（补启/重试路径防重复钩子）
            from gui.hotkey import GlobalHotkey
            if getattr(self, "_hotkeys", None) is None:
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
        """F10：紧急停止——释放全部按键 + 停止任务 + 停止录制 + HUD 提示。"""
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
            # 世界图轨迹录制同样停止（F10 对录制也生效——游戏内直接保存）
            wg = getattr(self, "world_graph", None)
            if wg is not None and getattr(wg, "_recorder", None) is not None \
                    and wg._recorder.recording:
                wg._toggle_record()  # 停止 + 保存 + HUD 收起
            # 兜底：无论录制状态，F10 都强制回收录制 HUD（防卡桌面）
            if wg is not None and hasattr(wg, "_force_hud_cleanup"):
                wg._force_hud_cleanup()
        except Exception:
            pass
        try:
            # 任务中心子进程任务同样停止（F10 对任何任务都生效）
            if getattr(self, "studio", None) is not None \
                    and getattr(self.studio, "_proc", None) is not None \
                    and self.studio._proc.running:
                self.studio._stop_task()
        except Exception:
            pass
        try:
            import ctypes
            # 兜底：释放 W/A/S/D/Esc/空格 的 keyup
            for vk in (0x57, 0x41, 0x53, 0x44, 0x1B, 0x20):
                ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)
            # 兜底：释放鼠标左/右键（长按中 F10 也必须松开）
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTBUTTONUP
            ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTBUTTONUP
        except Exception:
            pass
        if getattr(self, "_hud", None) is not None:
            self._hud.overlay.set_emergency()
        deck = self._deck()
        if deck is not None:
            deck.led.setText("⚠ F10 紧急停止（按键已释放）")
            deck.led.setStyleSheet("color: #E64545; font-size: 12px;")

    def _poll_health(self):
        """轮询消费 HealthWorker 结果（本环境 QThread 信号→QObject 槽不投递）。"""
        w = self._health_worker
        result = getattr(w, "_result", None)
        if result is None:
            # 窗口自愈（排查窗口消失）：非关闭流程中主窗口不可见 →
            # 500ms 内恢复显示。凶手是 hide/系统误关闭时直接自愈；
            # 对象已销毁则 show 抛错 → destroyed guard 已 os._exit 兜底。
            # 修复（0.6.0 审查）：最小化窗口不触发自愈（isVisible 对最小化
            # 也返回 False——否则用户最小化后 500ms 被强制恢复）
            if not self.isVisible() \
                    and not self.isMinimized() \
                    and not getattr(self, "_we_closing", False):
                try:
                    import time as _time
                    p = self._trace_log_path()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with open(p, "a", encoding="utf-8") as f:
                        f.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"self-heal: MainWindow 不可见 → show() 恢复\n")
                    self.show()
                except Exception:
                    pass
            return
        w._result = None  # 消费
        self._on_health_done(*result)

    def _refresh_health(self):
        """系统状态周期刷新：检测进行中跳过（防重入），完成后经轮询更新。"""
        if self._health_worker.isRunning():
            return
        self._health_worker.start()

    def _ensure_game_foreground(self):
        """检测游戏前台——不在则自动激活（任务运行期间才拉置顶）。

        修复（0.6.0 排查）：任务不在运行状态（失败/停止/空闲）直接返回——
        否则定时器残留会疯狂抢前台。
        """
        try:
            # 运行状态保护：仅 running 期间拉置顶
            mc = getattr(self, "mission_controller", None)
            if mc is not None:
                st = getattr(mc.state, "value", mc.state)
                if st != "running":
                    return
            import ctypes
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return  # 游戏没开——不打扰
            # HUD 补启：_start_hud 在窗口缺失时会直接跳过——游戏被自动拉起
            # 后此处补启（否则"开始任务后 HUD 不存在"）
            if getattr(self, "_hud", None) is None:
                self._start_hud()
                return
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

    def _deck(self):
        """安全取指挥台（构造失败时是 error_page——无 led/按钮，访问前判空）。"""
        d = getattr(self, "command_deck", None)
        return d if d is not None and hasattr(d, "led") else None

    def _on_health_done(self, health, error):
        # Bug 22/23：检测完成状态反馈（失败显示原因，不再静默）
        self._health = health or {}
        deck = self._deck()
        if deck is None:
            return
        if error:
            deck.set_health_status("环境检测失败: " + error[:120], busy=False)
        else:
            deck.set_health(health)
            # 健康提示：关键项失败给可行动原因（非管理员/前台）
            hints = []
            if health.get("admin") is False:
                hints.append("输入被拦（非管理员）→ 请以管理员运行")
            if health.get("foreground") is False and health.get("window"):
                hints.append("游戏窗口不在前台 → 切回游戏窗口")
            if hints:
                deck.set_health_status("；".join(hints), busy=False)
            else:
                deck.set_health_status("环境就绪", busy=False)
            self._sync_runtime_state()

    def _sync_runtime_state(self):
        """Bug 102：状态恢复——GUI 启动/重开时主动同步 runtime（不只等事件）。"""
        deck = self._deck()
        if deck is None:
            return
        st = getattr(self.mission_controller, "state", None)
        # BUG-012：状态可能为 str 或 Enum——统一取 value 比较（类型安全）
        if getattr(st, "value", st) == "running":
            deck.led.setText("● 运行中（恢复同步）")
            deck.led.setStyleSheet("color: #4FD1C5; font-size: 12px;")
            deck.start_btn.setEnabled(False)
            deck.stop_btn.setEnabled(True)

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
        # 审查：HUD 订阅泄漏——GUI 关闭必须 unsubscribe（bus 强引用
        # 阻止 GameHudController 释放，publish 会持续调已关闭的 _on_event）
        try:
            if getattr(self, "_hud", None) is not None:
                self._hud.destroy()
                self._hud = None
        except Exception:
            pass
        # 审查：F10 全局热键钩子泄漏——关闭必须 unhook（keyboard 钩子残留
        # 会持续回调到已销毁对象）
        try:
            if getattr(self, "_hotkeys", None) is not None:
                self._hotkeys.unregister_all()
                self._hotkeys = None
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

    @staticmethod
    def _trace_log_path():
        """退出探针日志路径（exit_trace.log）。"""
        from pathlib import Path as _P
        return _P(__file__).resolve().parent.parent / "logs" / "exit_trace.log"

    @staticmethod
    def _trace_close(msg):
        """关闭路径探针——直接文件写（不依赖 logging level）。"""
        try:
            import time as _time
            p = MainWindow._trace_log_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def closeEvent(self, event):
        # Bug 7：关闭顺序——先停 worker/取消订阅（杜绝后台线程继续发 GUI 信号），
        # 再停 Runtime（防后台继续点击），最后保存诊断
        # BUG-009：wait 超时（check_health 内部阻塞）→ 明确警告而非静默残留
        # 子进程模式（0.6.0 回滚）：m7 任务在独立 QProcess，kill 即停——
        # 无需 os._exit 兜底（那是进程内 QThread 集成的历史包袱）
        self._we_closing = True  # 关闭流程标记（窗口自愈跳过）
        self._trace_close("closeEvent entered")
        # 0.6.0 完善：录制中关窗口先停录制（钩子线程残留会持续注入/记录）
        try:
            import runtime.input.recorder as _rec_mod
            if _rec_mod._active_recorder is not None:
                rec = _rec_mod._active_recorder
                events = rec.stop()
                _rec_mod._active_recorder = None
                # 完善（第 8 轮）：关窗口停录制不丢数据——有事件就保存
                if events:
                    try:
                        path = rec.save()
                        if path is not None:
                            self._trace_close(
                                f"closeEvent 录制收尾保存: {path.name}"
                                f"（{len(events)} 事件）")
                    except Exception:
                        pass
        except Exception:
            pass
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
        # 任务中心：终止残留 m7 任务子进程（QProcess kill 即停，防孤儿继续点游戏）
        try:
            if getattr(self, "studio", None) is not None:
                self.studio.shutdown()
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("任务中心关闭失败")
        self._trace_close("closeEvent accepted — normal quit")
        self.shutdown()
        event.accept()
        # quitOnLastWindowClosed=False：显式退出事件循环（正常关闭路径唯一出口）
        try:
            from PySide6.QtWidgets import QApplication as _QA
            _app = _QA.instance()
            if _app is not None:
                _app.quit()
        except Exception:
            pass

    def refresh_command_deck(self):
        """录制同步后刷新指挥台（目标下拉 + 任务队列联动更新）。"""
        try:
            from knowledge.guides_loader import load_guide_targets, \
                load_guide_regions, sync_custom_map, custom_enabled_names
            # 第 8 轮：显式传当前启用集（原无参=全量启用——录制后刷新会
            # 把用户关掉的地图全开回来）
            sync_custom_map(custom_enabled_names())
            targets = []
            maps_dir = Path(__file__).resolve().parent.parent \
                / "knowledge" / "guides" / "maps"
            if maps_dir.is_dir():
                import json as _json
                for md in sorted(maps_dir.iterdir()):
                    if not md.is_dir():
                        continue
                    map_id = md.name
                    map_display_name = map_id
                    try:
                        _doc = _json.loads(
                            (md / "map.json").read_text(encoding="utf-8"))
                        map_display_name = _doc.get("name") or map_id
                    except Exception:
                        pass
                    try:
                        ts = load_guide_targets(map_id, types=["chest"])
                        regions = {r["id"]: r["name"]
                                   for r in load_guide_regions(map_id)}
                        for t in ts:
                            t["room"] = regions.get(t["region"], t["region"])
                            t["map_name"] = map_display_name
                        targets.extend(ts)
                    except Exception:
                        continue
            self._all_targets = targets
            deck = getattr(self, "command_deck", None)
            if deck is not None and hasattr(deck, "refresh_targets"):
                deck.refresh_targets(targets)
        except Exception as e:
            import logging
            logging.getLogger("gui.main_window").exception(
                "指挥台刷新失败: %s", e)

    def _on_guide_run(self, mdir, region):
        """攻略体系"执行此区域"：匹配知识包该区域的已采集目标 → 指挥台执行。

        知识包（black_tower_test）workflow 的 room 与地图集 region 同名；
        无匹配（骨架/其他地图）→ 明确提示。"""
        try:
            from runtime.knowledge_loader import KnowledgePackage
            from config.settings import ROOT
            pkg = KnowledgePackage(ROOT / "knowledge" / "source" / "black_tower_test")
            matched = []
            for c in pkg.chests:
                wf = pkg.workflow(c["id"])
                room = (wf or {}).get("room") if wf else None
                if room == region:
                    matched.append(c["id"])
            if not matched:
                deck = self._deck()
                if deck is not None:
                    deck.led.setText(
                        f"● 区域 {region} 暂无已采集点位（知识包无匹配 workflow）")
                    deck.led.setStyleSheet(
                        "color: #FFB454; font-size: 12px;")
                return
            # 切到指挥台并选中该区域 → 直接执行 matched（combo 匹配是 UX 高亮，
            # 执行不依赖 combo——之前 payload[1]==region 中文vs英文恒 False，
            # 导致实际跑的是"全部目标"）
            self.navigationInterface.setCurrentWidget(self.command_deck)
            deck = self.command_deck
            idx = deck.find_region_index(region) if hasattr(deck, "find_region_index") \
                else None
            if idx is not None:
                deck.target_combo.setCurrentIndex(idx)
            self._start_run(matched)
        except Exception:
            import logging
            logging.getLogger("gui.main_window").exception("攻略区域执行接线失败")

    @gui_safe
    def _start_run(self, targets):
        # Bug 21：防重复启动（连点/事件未达窗口期）
        # 审查 P0-6：stopped（手动停止）/gate_blocked（G3 拦截）也可重启——
        # 原集合缺这两态导致停止后按钮恢复但点击永久静默
        # 审查：state 可能是 MissionState 枚举或字符串——统一取 value 比较
        deck = self._deck()
        _st = getattr(self.mission_controller.state, "value",
                      self.mission_controller.state)
        if _st not in (
                "idle", "done", "crashed", "invalid",
                "stopped", "gate_blocked"):
            if _st == "paused":
                # 审查：paused 禁止启动——旧 runner 线程仍在人工介入/abort
                # 路径，此时 start 会双执行；明确提示而非静默（原静默 return
                # 造成"暂停后无法恢复"困惑）
                if deck is not None:
                    deck.led.setText(
                        "● 任务已暂停（人工介入）——等待自然结束或按 F10 停止后重试")
                    deck.led.setStyleSheet("color: #FFB454; font-size: 12px;")
            return
        # 真机前置校验（G3 会拦，但提前告知更好）
        # 修复（0.6.0 排查）：foreground 不拦截——程序会自动拉游戏置顶，
        # 用户点开始瞬间游戏不在前台是常态，拦截=点开始就报环境不对。
        # 仅 admin 硬拦截（非管理员输入被 UIPI 拦，拉了也白拉）。
        if deck is not None and getattr(self, "_health", None):
            h = self._health
            warns = []
            if h.get("admin") is False:
                warns.append("非管理员（输入会被 UIPI 拦截）")
            if warns:
                deck.led.setText("● 真机执行需先处理: " + "；".join(warns))
                deck.led.setStyleSheet("color: #FFB454; font-size: 12px;")
                deck.start_btn.setEnabled(True)
                deck.stop_btn.setEnabled(False)
                return
            if h.get("foreground") is False:
                # 提示但不阻断——启动流程会自动拉游戏置顶
                deck.led.setText("● 游戏窗口不在前台——将自动拉置顶")
                deck.led.setStyleSheet("color: #FFB454; font-size: 12px;")
        if deck is not None:
            deck.reset()
            deck.set_starting()  # Bug 30：同步禁按钮（不依赖事件）
        # 启动即时反馈（0.6.0：静默期=用户感知"没动静"）
        try:
            if deck is not None:
                deck.set_run_status("● 启动中：检查环境…", busy=True)
        except Exception:
            pass
        # 前台守护：开始任务即持续拉游戏置顶（用户要求）
        self.start_foreground_watch()
        try:
            # 第 62 轮：业务细节封装在 controller（路径/规格不再裸露在 GUI）
            self.mission_controller.start(targets)
        except Exception as e:
            # Bug 30：同步异常直接反馈（按钮不永久卡死）
            # 修复：启动失败即停前台守护（不再疯狂拉置顶）
            self.stop_foreground_watch()
            if deck is not None:
                deck.led.setText("● 启动失败: " + str(e)[:100])
                deck.start_btn.setEnabled(True)
                deck.stop_btn.setEnabled(False)

    @gui_safe
    def _stop_run(self):
        deck = self._deck()
        if deck is not None:
            deck.set_stopping()  # Bug 31：停止反馈先于结果
        # 修复：用户停止即停前台守护（不再抢前台）
        self.stop_foreground_watch()
        self.mission_controller.stop()

    def _on_runtime_event(self, event):
        # Bug 59/129：runner 线程可能调用本方法——只入队（deque append 原子），
        # 由主线程 QTimer 轮询消费（本环境跨线程 Qt 信号不可靠）。
        # 绝不在此直调 Qt 控件。
        self._runtime_queue.append(event)

    def _poll_runtime_events(self):
        """主线程轮询消费 runtime 事件队列（50ms）——合并刷新（Bug 129）。

        审查：deque.popleft 原子消费，不整体替换列表——原 list 替换在
        runner append 与主线程交换引用之间竞态会丢事件。
        """
        q = self._runtime_queue
        if not q:
            return
        events = []
        while q:
            try:
                events.append(q.popleft())
            except IndexError:
                break
        if events:
            self._flush_events(events)

    def _flush_events(self, events):
        # GUI 线程内执行——所有 Qt 控件操作都在这里
        deck = self._deck()
        for event in events:
            if deck is not None:
                deck.on_event(event)
            # 观察中心同步接收事件统计
            if hasattr(self.observation, "on_event"):
                self.observation.on_event(event)
            # 失败持久化（修复：失败日志落盘 memory/failures.jsonl——
            # 原来只发瞬时事件，重启即丢，失败检查器也是摆设）
            if event.type == "fail_recorded":
                try:
                    from runtime.failure_memory import FailureMemory
                    ctx = event.context or {}
                    FailureMemory().record(
                        failure=event.detail or "unknown",
                        context={"target": ctx.get("target"),
                                 "category": ctx.get("category"),
                                 "error": ctx.get("error"),
                                 "ts_human": event.created_at
                                 if hasattr(event, "created_at") else None})
                except Exception:
                    pass
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
            # 任务结束/报错 → HUD 收起（不再卡在游戏窗口）+ 停前台守护
            #（修复：失败后不再疯狂拉游戏置顶）
            if event.type in ("run_finished", "pause_requested") \
                    and getattr(self, "_hud", None) is not None:
                try:
                    self._hud.hide()
                except Exception:
                    pass
            if event.type == "run_finished":
                self.stop_foreground_watch()
