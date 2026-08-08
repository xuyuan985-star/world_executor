"""观察记忆（第 8 步 / 企划 C.1：两次独立观测确认）。

单帧观察（尤其 VLM）可能受瞬时画面影响——UI 动画/遮挡/加载帧。
稳定确认：同一 (room, ui_state) 连续命中 required 次才视为 STABLE，
供 Planner 决策前把关。

状态：UNKNOWN → CONFIRMING → STABLE；变化后 → UNSTABLE（重新确认）。
"""
from dataclasses import dataclass


@dataclass
class StableState:
    current: tuple = None    # (room, ui_state)
    previous: tuple = None   # 上一次（变化检测）
    hits: int = 0
    required: int = 2

    def update(self, obs):
        """obs → key 更新；返回是否已达稳定（hits >= required）。"""
        key = ((getattr(obs, "room", None), getattr(obs, "ui_state", None))
               if obs is not None else None)
        if key != self.current:
            self.previous = self.current
            self.current = key
            self.hits = 1
        else:
            self.hits += 1
        return self.hits >= self.required

    @property
    def label(self):
        if self.current is None:
            return "UNKNOWN"
        if self.hits >= self.required:
            return "STABLE"
        if self.previous is not None:
            return "UNSTABLE"     # 刚变化，重新确认中
        return "CONFIRMING"       # 首次观测，待第二次确认
