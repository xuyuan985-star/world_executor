"""Bug 230：点位数据迁移（v1 → v2 字段补全）。

v2 新增字段：coordinate_type / status / resolution / confidence / source_video。
v1 旧点位缺字段不删除——原地补默认值。

用法：python tools/migrate_points.py [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUIDES = ROOT / "knowledge" / "guides" / "maps"

POINTS_VERSION = 2


def migrate_item(p):
    changed = False
    if "coordinate_type" not in p:
        p["coordinate_type"] = "normalized"
        changed = True
    if "status" not in p:
        p["status"] = "pending_review"
        changed = True
    if "resolution" not in p:
        p["resolution"] = [1280, 720]
        changed = True
    if "confidence" not in p:
        p["confidence"] = None
        changed = True
    if "source_video" not in p:
        p["source_video"] = None
        changed = True
    return changed


def main():
    dry = "--dry-run" in sys.argv
    migrated = 0
    for md in sorted(GUIDES.iterdir()):
        pdir = md / "points"
        if not pdir.exists():
            continue
        for f in pdir.glob("*.json"):
            if f.name == "points_meta.json":
                continue
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(items, list):
                continue
            touched = False
            for p in items:
                if isinstance(p, dict) and migrate_item(p):
                    touched = True
            if touched:
                migrated += len(items)
                print(f"[migrate] {md.name}/{f.name}（{len(items)} 条 → v{POINTS_VERSION}）")
                if not dry:
                    tmp = f.with_name(f.name + ".tmp")
                    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
                    tmp.replace(f)
    print(f"MIGRATE {'DRY-RUN ' if dry else ''}DONE（涉及 {migrated} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
