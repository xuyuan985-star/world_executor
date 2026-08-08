"""ExecutionResult：#31 执行结果携带错误上下文与恢复策略。

调用方（orchestrator）不再只见 bool——retryable 决定重试策略：
  transient（点击偶发失败/加载等待）→ 重试
  permanent（模板不存在/权限不足/低置信）→ 不重试，直接失败报告
#17-A：code 为稳定错误枚举（ErrorCode），error 字符串仅展示——判定逻辑
优先走 code，杜绝字符串子串匹配腐化。
"""
from dataclasses import dataclass

from runtime.errors import ErrorCode


@dataclass
class ExecutionResult:
    success: bool
    error: str = None
    retryable: bool = True
    category: str = "F1"
    code: ErrorCode = None  # #17-A：稳定错误码（error 字符串的规范化形式）

    def to_context(self):
        ctx = {"success": self.success}
        if self.code is not None:
            ctx["code"] = self.code.value
        if self.error:
            ctx["error"] = self.error
        return ctx


def execution_failure(error, retryable=False, category="F1", code=None):
    return ExecutionResult(success=False, error=error, retryable=retryable,
                           category=category, code=code)
