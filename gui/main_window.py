from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # world_executor 根（AI 审计 B1）

from gui.pages.command_deck import CommandDeck
from gui.pages.placeholder import (KnowledgePage, ObservationPage, SettingsPage,
                                   StudioPage, WorldGraphPage)
from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition)

from gui.theme import apply_theme


class MainWindow(FluentWindow):
    event_received = Signal(object)

    def __init__(self, targets, event_bus, api, parent=None):
        super().__init__(parent)
        apply_theme(QApplication.instance())
        self.setWindowTitle("WorldExecutor Studio")
        self.setMinimumSize(1180, 720)

        self.command_deck = CommandDeck(targets)
        self.world_graph = WorldGraphPage()
        self.observation = ObservationPage()
        self.knowledge = KnowledgePage()
        self.studio = StudioPage()
        self.settings = SettingsPage()

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
        sub = QLabel("SPACE STATION CHEST HUNT")
        sub.setObjectName("brandSubLabel")
        title_bar.hBoxLayout.insertWidget(2, brand)
        title_bar.hBoxLayout.insertWidget(3, sub)

        self.event_bus = event_bus
        self.api = api
        self.event_bus.subscribe(self._on_runtime_event)
        self.command_deck.run_requested.connect(
            lambda targets: self._start_run(targets, self.command_deck.mode()))
        self.command_deck.stop_requested.connect(self._stop_run)

        from PySide6.QtCore import QThread, Signal

        class HealthWorker(QThread):
            done = Signal(dict, str)  # Bug 23：capability + 错误信息（不再吞异常）

            def run(self):
                # GUI-1：March7th 探测会 os.chdir(M7)（硬约束）——线程共享进程 cwd，
                # 不恢复会让后续相对路径解析错（validate 报缺 rooms.json → 点开始无反应）
                import os
                saved = os.getcwd()
                try:
                    from runtime.health import check_health
                    self.done.emit(check_health().get("capability", {}), "")
                except Exception as e:
                    self.done.emit({}, str(e))  # Bug 23：错误透传 GUI 显示
                finally:
                    try:
                        os.chdir(saved)
                    except Exception:
                        pass

        self._health_worker = HealthWorker(self)
        self.command_deck.set_health_status("正在检测环境...", busy=True)
        self._health_worker.done.connect(self._on_health_done)
        self._health_worker.start()

    def _on_health_done(self, health, error):
        # Bug 22/23：检测完成状态反馈（失败显示原因，不再静默）
        if error:
            self.command_deck.set_health_status("环境检测失败: " + error[:120], busy=False)
        else:
            self.command_deck.set_health(health)
            self.command_deck.set_health_status("环境就绪", busy=False)

    def closeEvent(self, event):
        if getattr(self, "_health_worker", None) is not None and self._health_worker.isRunning():
            self._health_worker.quit()
            self._health_worker.wait(1000)
        # #57：窗口销毁时取消事件订阅（防已删 Qt 信号被后续 publish 调用）
        if getattr(self, "event_bus", None) is not None:
            self.event_bus.unsubscribe(self._on_runtime_event)
        event.accept()

    def _start_run(self, targets, mode="dry"):
        # Bug 21：防重复启动（连点/事件未达窗口期）
        if self.api.state not in ("idle", "done", "crashed", "invalid"):
            return
        from runtime.api.commands import MissionSpec
        # Bug 6：模式显式化——dry 模拟 / real 真机（GUI 下拉选择）
        spec = MissionSpec(knowledge_dir=str(ROOT / "knowledge/source/black_tower_test"),
                           target_ids=targets or None,
                           mode=mode)
        self.command_deck.reset()
        self.command_deck.set_starting()  # Bug 30：同步禁按钮（不依赖事件）
        try:
            self.api.start_mission(spec)
        except Exception as e:
            # Bug 30：同步异常直接反馈（按钮不永久卡死）
            self.command_deck.led.setText("● 启动失败: " + str(e)[:100])
            self.command_deck.start_btn.setEnabled(True)
            self.command_deck.stop_btn.setEnabled(False)

    def _stop_run(self):
        self.command_deck.set_stopping()  # Bug 31：停止反馈先于结果
        self.api.stop()

    def _on_runtime_event(self, event):
        self.event_received.emit(event)
        self.command_deck.on_event(event)
