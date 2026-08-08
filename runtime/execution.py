"""ExecutionResult：#31 执行结果携带错误上下文与恢复策略。

调用方（orchestrator）不再只见 bool——retryable 决定重试策略：
  transient（点击偶发失败/加载等待）→ 重试
  permanent（模板不存在/权限不足/低置信）→ 不重试，直接失败报告
"""
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    success: bool
    error: str = None
    retryable: bool = True
    category: str = "F1"

    def to_context(self):
        ctx = {"success": self.success}
        if self.error:
            ctx["error"] = self.error
        return ctx


def execution_failure(error, retryable=False, category="F1"):
    return ExecutionResult(success=False, error=error, retryable=retryable, category=category)
