"""Bug 198：知识库层单元测试（错误分类/排序/去重/连通性）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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
        # Bug 105：连通性——图中孤立房间被检出（有向 portal 图）
        from ingest.compiler.validate_graph import validate
        d = self._pkg({
            "package.json": "{}",
            "rooms.json": {"spawn_room": "room_A",
                           "rooms": [{"id": "room_A"}, {"id": "room_B"},
                                     {"id": "room_C"}]},
            # 有向图：A→B 可达；C→A 但无人能到 C（C 在图中但不可达）
            "portals.json": [{"id": "door_ab", "from": "room_A", "to": "room_B"},
                             {"id": "door_ca", "from": "room_C", "to": "room_A"}],
            "chests.json": [{"id": "c1", "room": "room_C"}],
        })
        pkg = KnowledgePackage(d)
        errors, _ = validate(pkg, verbose=False)
        joined = "\n".join(errors)
        self.assertIn("room_C 不可达", joined)

    # ---- Bug 246：损坏/缺字段/错误类型数据覆盖 ----

    def test_broken_json(self):
        # 损坏 JSON → KnowledgeCorruptError（不是静默空包）
        d = self._pkg({"package.json": "{}",
                       "chests.json": '{"id": '})
        with self.assertRaises(KnowledgeCorruptError):
            KnowledgePackage(d)

    def test_missing_field_not_crash(self):
        # 缺字段点位：加载不崩，校验给 warning/error 而非异常
        from ingest.compiler.validate_graph import validate
        d = self._pkg({"package.json": "{}",
                       "rooms.json": {"spawn_room": "room_A",
                                      "rooms": [{"id": "room_A"}]},
                       "chests.json": [{"id": "c1", "room": "room_A"}]})
        pkg = KnowledgePackage(d)
        errors, warnings = validate(pkg, verbose=False)
        self.assertTrue(errors or warnings)  # 有反馈，不静默

    def test_wrong_type_chests(self):
        # chests 为 {} → 明确格式错误
        from ingest.compiler.validate_graph import validate
        d = self._pkg({"package.json": "{}",
                       "rooms.json": {"spawn_room": "room_A",
                                      "rooms": [{"id": "room_A"}]},
                       "chests.json": {}})
        pkg = KnowledgePackage(d)
        errors, _ = validate(pkg, verbose=False)
        joined = "\n".join(errors)
        self.assertIn("格式错误", joined)

    def test_environment_flag(self):
        # Bug 234：environment 标记可读（test 包不混入正式执行）
        d = self._pkg({"package.json": json.dumps({"environment": "test"})})
        pkg = KnowledgePackage(d)
        self.assertEqual(pkg.environment, "test")


if __name__ == "__main__":
    unittest.main()
