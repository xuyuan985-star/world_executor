# runtime/observation_store.py

```python
"""ObservationStore：世界实体 → 最近观测记录（#29 解耦 + #39/#40 时空约束）。

记录含 bbox/置信度/时间戳/帧号——executor 消费时校验时效与置信度，
拒绝"看到 3 秒前的位置"或"0.2 置信度的猜测"（Belief state 基础）。
"""
import time


class ObservationRecord:
    __slots__ = ("bbox", "timestamp", "confidence", "frame_id")

    def __init__(self, bbox, timestamp=None, confidence=None, frame_id=None):
        self.bbox = bbox                      # (x,y) 或 [x1,y1,x2,y2]（归一化 0-1）
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.confidence = confidence          # 0-1，None = 未知
        self.frame_id = frame_id              # 来源帧（可空）

    def is_stale(self, max_age=1.5):
        return time.time() - self.timestamp > max_age


class ObservationStore:
    def __init__(self, max_entries=64):
        self._data = {}
        self._max = max_entries

    def set(self, entity_id, bbox, confidence=None, frame_id=None):
        self._data[entity_id] = ObservationRecord(bbox, confidence=confidence, frame_id=frame_id)
        if len(self._data) > self._max:
            for k in list(self._data)[: len(self._data) - self._max]:
                del self._data[k]

    def get(self, entity_id):
        """#38：返回不可变快照（拷贝），observer/executor 各持一份——
        executor 读取期间 observer 更新不会看到半更新状态。"""
        rec = self._data.get(entity_id)
        if rec is None:
            return None
        return ObservationRecord(
            bbox=tuple(rec.bbox),
            timestamp=rec.timestamp,
            confidence=rec.confidence,
            frame_id=rec.frame_id,
        )

    def snapshot(self, entity_id):
        return self.get(entity_id)

    def clear(self):
        self._data.clear()

    def snapshot(self):
        return {k: v.bbox for k, v in self._data.items()}

```
