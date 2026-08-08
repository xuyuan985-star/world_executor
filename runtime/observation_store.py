"""ObservationStore：世界实体 → 最近观测的存储（#29 解耦）。

数据流：Observer（VLM/模板）产观测 → executor 消费后写入本 store →
executor 执行 vlm_bbox 时按实体读取。Executor 不依赖 Observer 模块，
只依赖中立 store——观察产物经显式通道进入执行层，无隐藏耦合。
"""


class ObservationStore:
    def __init__(self, max_entries=64):
        self._data = {}
        self._max = max_entries

    def set(self, entity_id, value):
        self._data[entity_id] = value
        if len(self._data) > self._max:
            for k in list(self._data)[: len(self._data) - self._max]:
                del self._data[k]

    def get(self, entity_id):
        return self._data.get(entity_id)

    def clear(self):
        self._data.clear()

    def snapshot(self):
        return dict(self._data)
