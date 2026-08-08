import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import apply_theme
from runtime.api.commands import RuntimeAPI
from runtime.events.bus import EventBus
from runtime.knowledge_loader import KnowledgePackage


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WorldExecutor Studio")
    apply_theme(app)

    pkg = KnowledgePackage(Path("knowledge/black_tower_test"))
    targets = pkg.chests or []
    bus = EventBus(persist_path="ingest/raw/events/studio.jsonl")
    api = RuntimeAPI(bus)
    window = MainWindow(targets, bus, api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
