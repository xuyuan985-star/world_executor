"""兼容层（第 7 步）：ActionIntent 定义已迁至 runtime/action_intent.py。

保留本文件仅为不破坏既有 import（orchestrator/step_executor）。
新代码请直接 `from runtime.action_intent import ...`。
"""
from runtime.action_intent import ActionIntent, ActionMethod, _deep_freeze  # noqa: F401
