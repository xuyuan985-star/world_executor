from runtime.input.base import InputBackend, InputResult


class MockBackend(InputBackend):
    """模拟后端（dry_run 使用）：不产生真实输入，全部成功。"""

    name = "mock"

    def click(self, x, y):
        return InputResult(success=True, action="click", backend=self.name, detail={"x": x, "y": y})

    def move(self, x, y):
        return InputResult(success=True, action="move", backend=self.name, detail={"x": x, "y": y})

    def press_key(self, key, wait_time=0.2):
        return InputResult(success=True, action="press_key", backend=self.name, detail={"key": key})
