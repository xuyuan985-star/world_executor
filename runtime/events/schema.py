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
    "pause_requested",
    "resume_checked",
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

OBSERVER_TYPES = {"template_match", "ocr", "ui_signal", "inferred", "manual", "vlm_vision"}

ACTION_CONTEXT_FIELDS = {
    "reason": "决策层意图，回答为什么执行（如 objective_verify_chest）",
    "source": "决定来源：decision_layer / manual / recovery",
    "naturalized": "是否经自然性约束",
    "delay_ms": "实际等待毫秒",
}


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


@dataclass
class Observation:
    """Observation Contract（v0.11 冻结）：所有观测必须构造此对象，禁止裸 dict。"""
    observer: str  # 必须是 OBSERVER_TYPES 之一
    target: str
    confidence: float
    timestamp: float
    context: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.observer not in OBSERVER_TYPES:
            raise ValueError(f"非法 observer: {self.observer}（允许: {sorted(OBSERVER_TYPES)}）")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence 越界: {self.confidence}")

    def to_event(self, execution_id, **kw):
        return WorldEvent(
            type="observation",
            execution_id=execution_id,
            detail=self.target,
            context={
                "observer": self.observer,
                "target": self.target,
                "confidence": self.confidence,
                "timestamp": self.timestamp,
                **self.context,
            },
            **kw,
        )
