"""BUG-069：workflow → chests 注册表同步——真点位注册进 chests.json。

legacy 假数据（chest_A-D）保留（mock/smoke 用）；真点位补注册。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PKG = ROOT / "knowledge/source/black_tower_test"
CHESTS = PKG / "chests.json"
WF_DIR = PKG / "workflows"


def main():
    items = json.loads(CHESTS.read_text(encoding="utf-8"))
    existing = {c.get("id") for c in items}
    added = 0
    for wf_file in sorted(WF_DIR.glob("*.json")):
        wf = json.loads(wf_file.read_text(encoding="utf-8"))
        tid = wf.get("target_id")
        if not tid or tid in existing:
            continue
        step = (wf.get("steps") or [{}])[0]
        items.append({
            "id": tid,
            "room": wf.get("room", "base_zone"),
            "template": step.get("template"),
            "threshold": step.get("threshold", 0.8),
            "scale_range": step.get("scale_range", [0.9, 1.1]),
            "verify_signal": step.get("verify", {}).get("ocr", [None])[0],
        })
        existing.add(tid)
        added += 1
    CHESTS.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"注册同步完成：新增 {added} 条真点位（共 {len(items)} 条）")


if __name__ == "__main__":
    main()
