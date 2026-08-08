from dataclasses import dataclass, field
from enum import Enum


class ActionMethod(Enum):
    """intent.method 白名单（#28）：字符串散落是 typo 源头，运行时才炸。"""
    TEMPLATE = "template"
    TEXT = "text"
    KEY = "key"
    VLM_BBOX = "vlm_bbox"


@dataclass
class ActionIntent:
    """动作意图：决策层产出，不携带任何坐标。

    语义约束（v0.12.1 Errata）：
    - target 一律为**世界实体 id**（chest_001 / lm_hall_center）或 UI 文字（method=text）；
      禁止模板文件名（chest_icon_v3.png 属于知识数据，由 executor 解析）。
    - method="vlm_bbox" 时位置来自该实体的**最近观测记录**（observation store），
      由 executor 解析绝对坐标——executor 知道"怎么点"，intent 决定"点什么"。
    """
    action: str          # interact | click_text | move | press_key
    target: str          # 世界实体 id / UI 文字
    method: str          # ActionMethod 值（构造时校验）
    params: dict = field(default_factory=dict)
    reason: str = None   # 决策意图（objective_verify_chest …）
    source: str = "decision_layer"
    idempotent: bool = True  # #32：非幂等动作（传送/确认/购买）禁止 retry
    execution_id: str = None  # #45：贯穿日志/失败关联（executor 执行时填充）

    def __post_init__(self):
        if self.method not in ActionMethod._value2member_map_:
            raise ValueError(f"非法 method: {self.method}（允许: {sorted(m.value for m in ActionMethod)}）")

    def to_context(self):
        ctx = {"action": self.action, "target": self.target, "method": self.method}
        if self.reason:
            ctx["reason"] = self.reason
        if self.execution_id:
            ctx["execution_id"] = self.execution_id
        ctx["source"] = self.source
        return ctx
