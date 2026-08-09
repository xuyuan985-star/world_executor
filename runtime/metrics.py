"""Bug 250：统一监控指标（MetricsCollector）——成功率/失败率/耗时/延迟。

进程级单例：任务、动作、视觉三个维度，可导出 JSON 快照。
"""
import threading
import time


class MetricsCollector:
    def __init__(self):
        self._lock = threading.Lock()
        self.tasks = {"total": 0, "done": 0, "failed": 0}
        self.actions = {"total": 0, "success": 0, "failed": 0,
                        "total_ms": 0.0}
        self.vision = {"template_matches": 0, "template_miss": 0,
                       "total_ms": 0.0}
        self.started_at = time.time()

    def task_done(self, success):
        with self._lock:
            self.tasks["total"] += 1
            self.tasks["done" if success else "failed"] += 1

    def action(self, success, ms):
        with self._lock:
            self.actions["total"] += 1
            self.actions["success" if success else "failed"] += 1
            self.actions["total_ms"] += ms

    def template_match(self, hit, ms):
        with self._lock:
            if hit:
                self.vision["template_matches"] += 1
            else:
                self.vision["template_miss"] += 1
            self.vision["total_ms"] += ms

    def snapshot(self):
        with self._lock:
            a = dict(self.actions)
            t = dict(self.tasks)
            v = dict(self.vision)
            uptime = time.time() - self.started_at
        return {
            "uptime_s": round(uptime, 1),
            "tasks": {**t, "success_rate": round(
                t["done"] / t["total"], 3) if t["total"] else None},
            "actions": {**a, "success_rate": round(
                a["success"] / a["total"], 3) if a["total"] else None,
                "avg_ms": round(a["total_ms"] / a["total"], 1)
                if a["total"] else None},
            "vision": {**v, "avg_ms": round(v["total_ms"] / (
                v["template_matches"] + v["template_miss"]), 1)
                if (v["template_matches"] + v["template_miss"]) else None},
        }


METRICS = MetricsCollector()
