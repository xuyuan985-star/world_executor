# runtime/events/bus.py

```python
import json
import threading
from collections import deque
from pathlib import Path

from runtime.events.schema import WorldEvent


# #34：内存事件流设上限（防长期运行无限增长）；持久化流不受限
EVENT_RING_CAPACITY = 5000


class EventBus:
    def __init__(self, persist_path=None):
        self._lock = threading.Lock()
        self._subscribers = []
        self._events = deque(maxlen=EVENT_RING_CAPACITY)
        self._seq = 0
        self._persist_path = persist_path
        self._fh = None
        if persist_path:
            Path(persist_path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(persist_path, "a", encoding="utf-8")

    def subscribe(self, callback):
        # BUG-28：订阅者列表并发修改（GUI 线程注册 / runner 线程 publish 快照）
        with self._lock:
            self._subscribers.append(callback)

    def publish(self, event: WorldEvent):
        with self._lock:
            self._seq += 1
            event.sequence_id = self._seq  # #33：按发布序打全局序号
            self._events.append(event)
            if self._fh:
                self._fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                self._fh.flush()
        for cb in list(self._subscribers):
            try:
                cb(event)
            except Exception as e:
                # #35：事件系统不能反向影响执行链——订阅者异常只记录
                import logging
                logging.getLogger("runtime.events").warning(
                    "subscriber error on %s: %s", event.type, e, exc_info=True)
        try:
            from runtime import db
            db.record_event(event)
        except Exception as e:
            import logging
            logging.getLogger("runtime.events").warning("db.record_event failed: %s", e)

    def replay(self, execution_id=None):
        with self._lock:
            events = list(self._events)
        if execution_id:
            events = [e for e in events if e.execution_id == execution_id]
        return events

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    @classmethod
    def load(cls, path):
        bus = cls()
        if Path(path).exists():
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:  # #12：半行/损坏日志跳过（断电场景）
                    data = json.loads(line)
                except Exception:
                    continue
                try:
                    bus._events.append(WorldEvent(**data))
                except Exception:
                    continue
        return bus


default_bus = EventBus()

```
