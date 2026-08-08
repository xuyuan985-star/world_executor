"""Planner（第 7 步：决策层——Observation → ActionIntent）。

禁止：点击 / OCR / VLM / Windows API——只做决策。
输入 Observation，输出 ActionIntent（frozen，零坐标）。
"""
from runtime.action_intent import ActionIntent, ActionMethod, ActionType
from runtime.observation import Observation
from runtime.world_state import WorldState


class Planner:
    """意图规划器。

    decide()：观察 → 动作意图（文本/实体检测语义）。
    plan_interact() / plan_wait()：直接构造意图（workflow 步骤路径也可用）。
    plan()：目标驱动（Sprint E-5）——状态校验 + 知识校验 + 步骤产出。
    """

    def __init__(self, default_threshold=0.8, max_retries=3, min_confidence=0.6):
        self.default_threshold = default_threshold
        self.max_retries = max_retries
        self.min_confidence = min_confidence  # #8-8：低于此置信不行动

    def decide(self, obs: Observation, target: str) -> ActionIntent:
        """观察 → 意图：目标文本出现在观测中且置信达门槛 → 点击意图；否则等待。

        不执行任何观测/输入（纯决策）。method 由观测来源决定：
        - 观测含 entities（VLM 定位过）→ template 实体点击
        - 文本命中（OCR）→ text 点击
        #8-8：confidence 低于门槛 → WAIT（防 Edge 截图 + VLM 高置信幻觉）
        """
        if obs is None or obs.confidence < self.min_confidence:
            return self.plan_wait(
                "low confidence" if obs is not None else "no observation")
        text = "".join(obs.text or [])
        if target in text:
            return self.plan_interact(target, method=ActionMethod.TEXT.value,
                                      reason="target detected in OCR text",
                                      confidence=obs.confidence)
        for ent in (obs.entities or []):
            if ent.get("id") == target and ent.get("confidence", 0) >= 0.6:
                return self.plan_interact(target, method=ActionMethod.TEMPLATE.value,
                                          reason="target entity located",
                                          confidence=ent.get("confidence", 0.0))
        return self.plan_wait("target missing")

    def plan_interact(self, target, method=None, reason="", confidence=0.0,
                      vision_verified=False, vision_confidence=0.0,
                      evidence_id=None, risk="low"):
        return ActionIntent(
            action=ActionType.INTERACT.value,
            target=target,
            method=method or ActionMethod.TEMPLATE.value,
            params={"threshold": self.default_threshold,
                    "max_retries": self.max_retries},
            reason=reason or "objective_interact",
            source="planner",
            idempotent=True,
            # Sprint B-2：视觉证明透传（observe_act 通道由 gate 写入）
            vision_verified=vision_verified,
            vision_confidence=vision_confidence,
            evidence_id=evidence_id,
            risk=risk,
        )

    def plan(self, state: WorldState, goal: str, pkg=None):
        """Sprint E-5：目标驱动规划。

        goal 映射 knowledge workflows；校验前置（room 匹配）后产出步骤意图。
        返回 {"plan": [ActionIntent...], "status": "planned|already_done|blocked",
              "reason": "..."}。
        """
        if state is None:
            return {"plan": [], "status": "blocked", "reason": "no_world_state"}
        workflow = None
        if pkg is not None:
            workflow = pkg.workflow(goal)  # 知识包按 target_id 单文件加载
        if workflow is None:
            return {"plan": [], "status": "blocked", "reason": f"goal_unknown:{goal}"}

        # 房间前置校验：workflow 声明 room → 当前状态必须匹配
        need_room = workflow.get("room")
        if need_room and state.room and need_room != state.room:
            return {"plan": [], "status": "blocked",
                    "reason": f"room_mismatch:need={need_room},have={state.room}"}
        if goal in state.completed:
            return {"plan": [], "status": "already_done", "reason": "completed"}

        # 步骤 → 意图（move/interact 语义；verify 不产意图——由执行后校验闭环）
        plan = []
        for step in (workflow.get("steps") or []):
            st = step.get("type")
            if st == "move":
                plan.append(self.plan_interact(
                    step.get("target"), method=ActionMethod.TEMPLATE.value,
                    reason=f"objective_navigate:{goal}"))
            elif st == "interact":
                plan.append(self.plan_interact(
                    workflow.get("target_id") or step.get("target"),
                    method=ActionMethod.TEMPLATE.value,
                    reason=f"objective_interact:{goal}"))
        return {"plan": plan, "status": "planned", "reason": "ok"}

    def plan_wait(self, reason="wait"):
        return ActionIntent(
            action=ActionType.WAIT.value,
            target=None,
            method=ActionMethod.TEXT.value,
            reason=reason,
            source="planner",
            idempotent=False,
        )

    @staticmethod
    def action_of(intent: ActionIntent) -> ActionType:
        """ActionIntent.action 字符串 → ActionType（未知兜底 NONE）。"""
        try:
            return ActionType(intent.action)
        except ValueError:
            return ActionType.NONE
