"""Bug 198：知识库层单元测试（错误分类/排序/去重/连通性）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.knowledge_loader import (DuplicateIDError, KnowledgeCorruptError,
                                      KnowledgePackage)


class TestKnowledgePackage(unittest.TestCase):
    def _pkg(self, files):
        d = Path(tempfile.mkdtemp())
        for name, content in files.items():
            (d / name).write_text(json.dumps(content) if not isinstance(content, str)
                                  else content, encoding="utf-8")
        return d

    def test_corrupt_json_classified(self):
        # Bug 101：损坏 → KnowledgeCorruptError（不是空包）
        d = self._pkg({"package.json": '{"name":'})
        with self.assertRaises(KnowledgeCorruptError):
            KnowledgePackage(d)

    def test_duplicate_id_rejected(self):
        # Bug 103：重复 id → DuplicateIDError
        d = self._pkg({"package.json": "{}",
                       "chests.json": [{"id": "c1"}, {"id": "c1"}]})
        with self.assertRaises(DuplicateIDError):
            KnowledgePackage(d)

    def test_sorted_chests(self):
        # Bug 104：加载顺序稳定
        d = self._pkg({"package.json": "{}",
                       "chests.json": [{"id": "chest_10"}, {"id": "chest_2"},
                                       {"id": "chest_1"}]})
        pkg = KnowledgePackage(d)
        self.assertEqual([c["id"] for c in pkg.chests],
                         ["chest_1", "chest_10", "chest_2"])

    def test_unreachable_rooms(self):
        # Bug 105：连通性——孤立房间被检出
        from ingest.compiler.validate_graph import validate
        d = self._pkg({
            "package.json": "{}",
            "rooms.json": {"spawn_room": "room_A",
                           "rooms": [{"id": "room_A"}, {"id": "room_C"}]},
            "chests.json": [{"id": "c1", "room": "room_C"}],
        })
        pkg = KnowledgePackage(d)
        errors, _ = validate(pkg, verbose=False)
        joined = "\n".join(errors)
        self.assertIn("room_C 不可达", joined)


if __name__ == "__main__":
    unittest.main()
