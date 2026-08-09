"""MissionController（第 62 轮重构）：UI 与 RuntimeAPI 之间的业务封装。

MainWindow 不再知道 MissionSpec/知识路径——只调 controller.start/stop。
"""
from PySide6.QtCore import QObject
from pathlib import Path

from config.settings import ROOT
from runtime.api.commands import MissionSpec


class MissionController(QObject):
    def __init__(self, runtime, knowledge_dir=None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        # Bug 4：知识库路径基于仓库根绝对定位（任意 cwd 启动不失效）
        self.knowledge_dir = knowledge_dir or str(
            ROOT / "knowledge" / "source" / "black_tower_test")

    def start(self, targets, mode="dry"):
        """GUI 语义化启动（路径/规格封装在 controller 内）。"""
        spec = MissionSpec(knowledge_dir=self.knowledge_dir,
                           target_ids=targets or None,
                           mode=mode)
        self.runtime.start_mission(spec)

    def stop(self):
        self.runtime.stop()

    def set_map(self, knowledge_dir):
        """Bug 94：地图切换 → 换知识目录并刷新（旧目标缓存不再残留）。"""
        if knowledge_dir:
            self.knowledge_dir = str(
                ROOT / knowledge_dir if not Path(knowledge_dir).is_absolute()
                else knowledge_dir)

    @property
    def state(self):
        return self.runtime.state
