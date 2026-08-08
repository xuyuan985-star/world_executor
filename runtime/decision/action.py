from dataclasses import dataclass, field


@dataclass
class ActionIntent:
    """动作意图：决策层产出，不携带任何坐标。

    坐标属于执行细节：VLM 定位结果只进 observation 事件，
    executor 消费"最近的定位观测"自行换算绝对坐标。
    """
    action: str          # interact | click_text | move | press_key
    target: str          # 知识包目标 id / 模板文件名 / 文字 / 按键
    method: str          # template | text | key
    params: dict = field(default_factory=dict)
    reason: str = None   # 决策意图（objective_verify_chest …）
    source: str = "decision_layer"

    def to_context(self):
        ctx = {"action": self.action, "target": self.target, "method": self.method}
        if self.reason:
            ctx["reason"] = self.reason
        ctx["source"] = self.source
        return ctx
