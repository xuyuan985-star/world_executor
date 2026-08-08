from dataclasses import dataclass, field


@dataclass
class InputResult:
    success: bool
    action: str
    backend: str
    error: str = None
    detail: dict = field(default_factory=dict)

    def to_context(self, **extra):
        ctx = {"backend": self.backend, "success": self.success}
        if self.error:
            ctx["error"] = self.error
        ctx.update(self.detail)
        ctx.update(extra)
        return ctx


class InputBackend:
    name = "base"

    def click(self, x, y) -> InputResult:
        raise NotImplementedError

    def move(self, x, y) -> InputResult:
        raise NotImplementedError

    def press_key(self, key, wait_time=0.2) -> InputResult:
        raise NotImplementedError
