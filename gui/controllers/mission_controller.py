"""MissionController（第 62 轮重构）：UI 与 RuntimeAPI 之间的业务封装。

MainWindow 不再知道 MissionSpec/知识路径——只调 controller.start/stop。
"""
from PySide6.QtCore import QObject

from runtime.api.commands import MissionSpec


class MissionController(QObject):
    def __init__(self, runtime, knowledge_dir=None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.knowledge_dir = knowledge_dir or "knowledge/source/black_tower_test"

    def start(self, targets, mode="dry"):
        """GUI 语义化启动（路径/规格封装在 controller 内）。"""
        spec = MissionSpec(knowledge_dir=self.knowledge_dir,
                           target_ids=targets or None,
                           mode=mode)
        self.runtime.start_mission(spec)

    def stop(self):
        self.runtime.stop()

    @property
    def state(self):
        return self.runtime.state
