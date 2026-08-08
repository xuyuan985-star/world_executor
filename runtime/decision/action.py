from dataclasses import dataclass, field


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
    method: str          # template | text | key | vlm_bbox
    params: dict = field(default_factory=dict)
    reason: str = None   # 决策意图（objective_verify_chest …）
    source: str = "decision_layer"

    def to_context(self):
        ctx = {"action": self.action, "target": self.target, "method": self.method}
        if self.reason:
            ctx["reason"] = self.reason
        ctx["source"] = self.source
        return ctx

