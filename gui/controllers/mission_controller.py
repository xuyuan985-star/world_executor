"""MissionController（第 62 轮重构）：UI 与 RuntimeAPI 之间的业务封装。

MainWindow 不再知道 MissionSpec/知识路径——只调 controller.start/stop。
第七轮审查（BUG-052~057）：持久化重写——
  BUG-052：完成状态绑定知识包（pkg_key，跨版本不污染）
  BUG-053：单 key 原子保存（version/completed/timestamp 一次写入）
  BUG-054：损坏状态显式报错（不静默降级为空）
  BUG-055：completed 合法性校验（不在当前目标集 → 告警）
  BUG-056：审计失败日志化（不静默）
  BUG-057：地图隔离（key 含 pkg_key，切换不串状态）
"""
import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import QObject

from config.settings import ROOT
from runtime.api.commands import MissionSpec


class StateCorruptionError(RuntimeError):
    """BUG-054：完成状态损坏——需人工处理（不静默当空）。"""


class MissionController(QObject):
    STATE_VERSION = 3

    # P1-006：必须 RLock——record_completed 内再调 completed_targets() 会二次获取
    _persist_lock = threading.RLock()

    def __init__(self, runtime, knowledge_dir=None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        # Bug 4：知识库路径基于仓库根绝对定位（任意 cwd 启动不失效）
        self.knowledge_dir = knowledge_dir or str(
            ROOT / "knowledge" / "source" / "black_tower_test")

    # ---------- 持久化（BUG-052/053/057） ----------

    def _pkg_key(self):
        """知识包身份键：路径 hash——切换知识目录即换状态域（BUG-057）。"""
        return hashlib.sha256(self.knowledge_dir.encode()).hexdigest()[:12]

    def _state_key(self):
        return f"mission_state:{self._pkg_key()}"

    def _load_state(self):
        """读取完成状态；损坏 → StateCorruptionError（BUG-054）。"""
        from PySide6.QtCore import QSettings
        s = QSettings("WorldExecutor", "Studio")
        raw = s.value(self._state_key())
        if raw is None:
            return {"version": self.STATE_VERSION, "completed": [],
                    "saved_at": None}
        if not isinstance(raw, dict):
            raise StateCorruptionError(
                f"完成状态损坏（类型 {type(raw).__name__}）：{str(raw)[:80]}")
        if raw.get("version") != self.STATE_VERSION:
            raise StateCorruptionError(
                f"完成状态版本不匹配（{raw.get('version')} != {self.STATE_VERSION}）")
        completed = raw.get("completed", [])
        if not isinstance(completed, list) or \
                not all(isinstance(c, str) for c in completed):
            raise StateCorruptionError("完成列表结构损坏（非字符串列表）")
        return raw

    def completed_targets(self):
        with self._persist_lock:
            return list(self._load_state().get("completed", []))

    def record_completed(self, target_ids):
        import time
        from PySide6.QtCore import QSettings
        with self._persist_lock:
            state = self._load_state()
            done = set(state.get("completed", []))
            done.update(target_ids)
            # BUG-053：单 key 原子写（版本/完成列表/时间戳一次保存）
            state = {"version": self.STATE_VERSION,
                     "completed": sorted(done),
                     "saved_at": time.time()}
            s = QSettings("WorldExecutor", "Studio")
            s.setValue(self._state_key(), state)

    def pending_targets(self, all_targets):
        done = set(self.completed_targets())
        # BUG-055：完成记录合法性——不在当前目标集 → 告警（跨版本残留）
        known = set(all_targets)
        unknown = done - known
        if unknown:
            import logging
            logging.getLogger("gui.mission_controller").warning(
                "完成记录含未知目标（知识包版本变化？）: %s", sorted(unknown)[:5])
        return [t for t in all_targets if t not in done]

    def set_map(self, knowledge_dir):
        """Bug 94/057：地图切换 → 换知识目录（状态域随 pkg_key 自动隔离）。"""
        if knowledge_dir:
            self.knowledge_dir = str(
                ROOT / knowledge_dir if not Path(knowledge_dir).is_absolute()
                else knowledge_dir)

    # ---------- 任务控制 ----------

    def start(self, targets, mode="dry"):
        """GUI 语义化启动（路径/规格封装在 controller 内）。"""
        self._audit(f"start mode={mode} targets={len(targets or [])}")
        spec = MissionSpec(knowledge_dir=self.knowledge_dir,
                           target_ids=targets or None,
                           mode=mode)
        self.runtime.start_mission(spec)

    def stop(self):
        self._audit("stop")
        self.runtime.stop()

    @staticmethod
    def _audit(action):
        """Bug 297：用户操作审计（append-only 日志）。
        BUG-056：写入失败日志化（审计链不可静默断）。"""
        import logging
        import time
        try:
            log_dir = ROOT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "user_action.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {action}\n")
        except Exception:
            logging.getLogger("gui.mission_controller").exception(
                "用户操作审计写入失败: %s", action)

    @property
    def state(self):
        return self.runtime.state
