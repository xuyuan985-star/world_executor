# runtime/recovery/manager.py

```python
"""RecoveryManager（Sprint D-9：长期运行关键——窗口/截图异常自动恢复）。

状态流：RUNNING → CAPTURE_FAIL → RETRY_CAPTURE(×N) → 恢复 | WINDOW_RECOVERY → STOP。
单次异常不死机：截图失败重试 → 窗口丢失重检 → 明确停止（可挂机数小时）。
"""
import time


class RecoveryManager:
    def __init__(self, capture_fn=None, window_check_fn=None,
                 max_capture_retries=3, retry_delay=1.0):
        self.capture_fn = capture_fn        # () -> bool 截图是否成功
        self.window_check_fn = window_check_fn  # () -> bool 窗口是否存活
        self.max_capture_retries = max_capture_retries
        self.retry_delay = retry_delay
        self.stats = {"capture_fail": 0, "window_loss": 0, "recovered": 0, "stopped": 0}

    def recover_capture(self):
        """截图失败 → 重试 N 次 → 仍败 → 窗口重检。

        返回 "ok" | "window_loss" | "stopped"。
        """
        for i in range(self.max_capture_retries):
            if self.capture_fn is None or self.capture_fn():
                if i > 0:
                    self.stats["recovered"] += 1
                return "ok"
            time.sleep(self.retry_delay * (i + 1))  # 退避
        self.stats["capture_fail"] += 1
        return self.recover_window()

    def recover_window(self):
        """窗口丢失 → 重检；仍无 → 停止（不再盲目操作）。"""
        for _ in range(2):
            time.sleep(self.retry_delay)
            if self.window_check_fn is None or self.window_check_fn():
                self.stats["recovered"] += 1
                return "ok"
        self.stats["window_loss"] += 1
        self.stats["stopped"] += 1
        return "stopped"

    def to_context(self):
        return dict(self.stats)

```
