from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel

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
        self.command_deck.run_requested.connect(self._start_run)
        self.command_deck.stop_requested.connect(self._stop_run)

        from PySide6.QtCore import QThread, Signal

        class HealthWorker(QThread):
            done = Signal(dict)

            def run(self):
                from runtime.health import check_health
                try:
                    self.done.emit(check_health().get("capability", {}))
                except Exception:
                    self.done.emit({})

        self._health_worker = HealthWorker(self)
        self._health_worker.done.connect(self.command_deck.set_health)
        self._health_worker.start()

    def closeEvent(self, event):
        if getattr(self, "_health_worker", None) is not None and self._health_worker.isRunning():
            self._health_worker.quit()
            self._health_worker.wait(1000)
        event.accept()

    def _start_run(self, targets):
        from runtime.api.commands import MissionSpec
        spec = MissionSpec(knowledge_dir="knowledge/source/black_tower_test",
                           target_ids=targets or None)
        self.command_deck.reset()
        self.api.start_mission(spec)

    def _stop_run(self):
        self.api.stop()

    def _on_runtime_event(self, event):
        self.event_received.emit(event)
        self.command_deck.on_event(event)
