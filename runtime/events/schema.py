import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

EVENT_TYPES = {
    "run_started",
    "run_finished",
    "state_changed",
    "observation",
    "action_executed",
    "target_progress",
    "fail_recorded",
    "repair_recorded",
}

STATE_TYPES = {
    "INIT",
    "CHECK_WORLD_STATE",
    "NAVIGATING",
    "PORTAL_TRANSITION",
    "PORTAL_TRANSITION_FAILED",
    "VERIFYING",
    "INTERACTING",
    "EVENT_INTERRUPT",
    "RECOVERING",
    "DONE",
    "ABORT",
}

OBSERVER_TYPES = {"template_match", "ocr", "ui_signal", "inferred", "manual"}


@dataclass
class WorldEvent:
    type: str
    execution_id: str
    context: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    time: float = field(default_factory=lambda: time.time())
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        if self.from_state is None:
            del d["from_state"]
        if self.to_state is None:
            del d["to_state"]
        if self.detail is None:
            del d["detail"]
        return d


def make_event(event_type, execution_id, **kw):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"非法事件类型: {event_type}")
    return WorldEvent(type=event_type, execution_id=execution_id, **kw)
