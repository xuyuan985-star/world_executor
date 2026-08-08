"""ReplayInput（第 9 步：回放驱动——测试确定性输入）。

按预置结果队列顺序返回（耗尽后全部 False），替代 FakeDriver 的
手工 mock——测试即回放脚本，行为完全确定。
实现 InputBackendProtocol 全套。
"""
from runtime.input.base import InputResult


class ReplayInput:
    """从 results 队列依次弹出的确定性输入后端。"""

    name = "replay"

    def __init__(self, results=None):
        self.results = list(results or [])
        self.index = 0
        self.available = True

    def _next(self, action):
        if self.index >= len(self.results):
            ok = False
        else:
            ok = bool(self.results[self.index])
            self.index += 1
        return InputResult(success=ok, action=action, backend=self.name,
                           error=None if ok else "replay_denied")

    @property
    def consumed(self):
        return self.index

    def click(self, x, y) -> InputResult:
        return self._next("click")

    def press_key(self, key, wait_time=0.2) -> InputResult:
        return self._next("press_key")

    def release_key(self, key) -> InputResult:
        return self._next("release_key")

    def click_template(self, path, threshold, max_retries) -> InputResult:
        return self._next("click_template")

    def click_text(self, text, include, max_retries, crop) -> InputResult:
        return self._next("click_text")
