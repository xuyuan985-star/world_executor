from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class InputResult:
    success: bool
    action: str
    backend: str
    error: str = None
    method: str = None   # backend 执行方法（#11）：template/text/key——action 保持 intent 语义
    detail: dict = field(default_factory=dict)

    def to_context(self, **extra):
        ctx = {"backend": self.backend, "success": self.success}
        if self.error:
            ctx["error"] = self.error
        if self.method:
            ctx["method"] = self.method
        ctx.update(self.detail)
        ctx.update(extra)
        return ctx


@runtime_checkable
class InputBackendProtocol(Protocol):
    """#20-3.7：输入后端契约——Fake 与真实实现都必须满足，防接口漂移。

    Fake 测试 PASS 而真机失败的主因之一 = 假实现签名漂移；测试侧
    断言 isinstance(fake, InputBackendProtocol) 即可防漂移。
    """
    name: str

    def click(self, x, y) -> InputResult: ...

    def press_key(self, key, wait_time=0.2) -> InputResult: ...

    def release_key(self, key) -> InputResult: ...

    def click_template(self, path, threshold, max_retries, scale_range=None) -> InputResult: ...

    def click_text(self, text, include, max_retries, crop) -> InputResult: ...


class InputBackend:
    name = "base"

    def click(self, x, y) -> InputResult:
        raise NotImplementedError

    def move(self, x, y) -> InputResult:
        raise NotImplementedError

    def press_key(self, key, wait_time=0.2) -> InputResult:
        raise NotImplementedError

    def release_key(self, key) -> InputResult:
        """#42：紧急释放（keyDown→keyUp 异常后兜底，防卡键）。"""
        raise NotImplementedError
