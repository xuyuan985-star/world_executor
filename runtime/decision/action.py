import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


def _deep_freeze(value):
    """#17-B：递归不可变化——MappingProxyType 只冻结表层 dict，
    嵌套 dict/list/set 仍可被改写（planner 偷偷改 intent 的隐患）。"""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(v) for v in value)
    return value


class ActionMethod(Enum):
    """intent.method 白名单（#28）：字符串散落是 typo 源头，运行时才炸。"""
    TEMPLATE = "template"
    TEXT = "text"
    KEY = "key"
    VLM_BBOX = "vlm_bbox"


@dataclass(frozen=True)
class ActionIntent:
    """动作意图：决策层产出，不携带任何坐标。

    #35 不可变契约：
    - frozen + params=MappingProxyType——执行期间任何层（callback/retry/planner）
      都无法原地改写意图，防止"第一次 threshold=0.85，retry 后变 0.95"的隐式漂移。
    - id：意图唯一键（#39b），action_started/action_completed 事件按 id 关联。

    语义约束（v0.12.1 Errata）：
    - target 一律为**世界实体 id**（chest_001 / lm_hall_center）或 UI 文字（method=text）；
      禁止模板文件名（chest_icon_v3.png 属于知识数据，由 executor 解析）。
    - method="vlm_bbox" 时位置来自该实体的**最近观测记录**（observation store），
      由 executor 解析绝对坐标——executor 知道"怎么点"，intent 决定"点什么"。
    """
    action: str          # interact | click_text | move | press_key
    target: str          # 世界实体 id / UI 文字
    method: str          # ActionMethod 值（构造时校验）
    params: Mapping = field(default_factory=dict)
    reason: str = None   # 决策意图（objective_verify_chest …）
    source: str = "decision_layer"
    idempotent: bool = True  # #32：非幂等动作（传送/确认/购买）禁止 retry
    execution_id: str = None  # #45：贯穿日志/失败关联（构造时由执行链传入）
    id: str = field(default_factory=lambda: f"int_{uuid.uuid4().hex[:8]}")
    preconditions: tuple = ()  # S5：执行前世界事实断言（契约先行，校验器接入前恒过）

    def __post_init__(self):
        if self.method not in ActionMethod._value2member_map_:
            raise ValueError(f"非法 method: {self.method}（允许: {sorted(m.value for m in ActionMethod)}）")
        object.__setattr__(self, "params", _deep_freeze(self.params))

    def to_context(self):
        ctx = {"action": self.action, "target": self.target, "method": self.method,
               "intent_id": self.id}
        if self.reason:
            ctx["reason"] = self.reason
        if self.execution_id:
            ctx["execution_id"] = self.execution_id
        ctx["source"] = self.source
        return ctx
