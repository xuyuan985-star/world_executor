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
        # Bug 291/293/294：模型调用指标（token 成本/延迟/错误分类）
        self.models = {"calls": 0, "total_ms": 0.0,
                       "prompt_tokens": 0, "completion_tokens": 0,
                       "errors": {"timeout": 0, "rate_limit": 0, "auth": 0,
                                  "invalid_json": 0, "other": 0}}
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

    def model_call(self, ms, prompt_tokens=0, completion_tokens=0, error=None):
        """Bug 291/293/294：模型调用统计（耗时/token/错误分类）。"""
        with self._lock:
            self.models["calls"] += 1
            self.models["total_ms"] += ms
            self.models["prompt_tokens"] += prompt_tokens or 0
            self.models["completion_tokens"] += completion_tokens or 0
            if error:
                cls = "other"
                if "timeout" in error.lower() or "timed out" in error.lower():
                    cls = "timeout"
                elif "quota" in error.lower() or "429" in error:
                    cls = "rate_limit"
                elif "401" in error or "auth" in error.lower():
                    cls = "auth"
                elif "json" in error.lower() or "parse" in error.lower():
                    cls = "invalid_json"
                self.models["errors"][cls] += 1

    def snapshot(self):
        with self._lock:
            a = dict(self.actions)
            t = dict(self.tasks)
            v = dict(self.vision)
            m = dict(self.models)
            m["errors"] = dict(m["errors"])
            m["avg_ms"] = round(m["total_ms"] / m["calls"], 1) if m["calls"] else None
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
            "models": m,
        }


METRICS = MetricsCollector()
