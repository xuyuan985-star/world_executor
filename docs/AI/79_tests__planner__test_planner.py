# tests/planner/test_planner.py

```python
"""Planner 测试（Sprint E-12：目标驱动规划）。

Test 1：goal=chest_A + state=room_A（匹配）→ planned（产出 interact 意图）
Test 2：goal=chest_A + state=room_B（不匹配）→ blocked room_mismatch
Test 3：goal 已完成 → already_done
Test 4：failure memory 记录/查询/计数

用法：python tests/planner/test_planner.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.planner import Planner  # noqa: E402
from runtime.world_state import WorldState  # noqa: E402
from runtime.knowledge_loader import KnowledgePackage  # noqa: E402

KNOWLEDGE = ROOT / "knowledge" / "source" / "black_tower_test"


def main():
    pkg = KnowledgePackage(KNOWLEDGE)
    planner = Planner()

    # Test 1：正确房间 → planned
    r1 = planner.plan(WorldState(room="room_A", ui="game"), "chest_A", pkg)
    assert r1["status"] == "planned", r1
    assert any(i.target for i in r1["plan"]), r1

    # Test 2：错误房间 → blocked（workflow 声明 room 时）
    class FakePkg:
        def workflow(self, target_id):
            return {"target_id": target_id,
                    "room": "room_A",
                    "steps": [{"type": "interact", "target": "x"}]}
    r2 = planner.plan(WorldState(room="room_B", ui="game"), "chest_A", FakePkg())
    assert r2["status"] == "blocked", r2
    assert "room_mismatch" in r2["reason"], r2

    # Test 3：已完成 → already_done
    st = WorldState(room="room_A", ui="game", completed=["chest_A"])
    r3 = planner.plan(st, "chest_A", pkg)
    assert r3["status"] == "already_done", r3

    # Test 4：FailureMemory
    import tempfile
    from pathlib import Path as _P
    from runtime.failure_memory import FailureMemory
    mem = FailureMemory(_P(tempfile.mkdtemp()) / "failures.jsonl")
    mem.record("click_failed", {"target": "chest_A", "room": "shop"},
               solution="retry_with_foreground")
    assert mem.count("click_failed") == 1
    assert mem.count("click_failed", target="chest_A") == 1
    assert mem.count("click_failed", target="other") == 0
    q = mem.query("click_failed", target="chest_A")
    assert q and q[0]["solution"] == "retry_with_foreground"

    print("[planner] Test 1-4（planned/room_mismatch/already_done/failure memory）全部 PASS")


if __name__ == "__main__":
    main()

```
