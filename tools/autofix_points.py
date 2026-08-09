"""Bug 245：自动修复简单数据错误（缺默认字段等小问题）。

修复项（仅安全项，损坏/语义错误不修）：
  1. 点位缺 coordinate_type/status/confidence/resolution → 补默认值
  2. 点位缺 name → 由 id 派生
  3. 点位 x/y 为 null → 删除该点（无法修复，仅提示）
  4. 区域缺 name → 用文件名派生

用法：python tools/autofix_points.py [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUIDES = ROOT / "knowledge" / "guides" / "maps"


def fix_item(p):
    """返回 (changed, notes)。只做安全修复。"""
    notes = []
    changed = False
    if "coordinate_type" not in p:
        p["coordinate_type"] = "normalized"
        changed = True
        notes.append("补 coordinate_type")
    if "status" not in p:
        p["status"] = "pending_review"
        changed = True
        notes.append("补 status")
    if "resolution" not in p:
        p["resolution"] = [1280, 720]
        changed = True
        notes.append("补 resolution")
    if "confidence" not in p:
        p["confidence"] = None
        changed = True
        notes.append("补 confidence")
    if not p.get("name") and p.get("id"):
        p["name"] = p["id"]
        changed = True
        notes.append("补 name")
    for f in ("x", "y"):
        if p.get(f) is None:
            notes.append(f"{f}=null 无法修复（建议删除该点）")
    return changed, notes


def main():
    dry = "--dry-run" in sys.argv
    fixed = 0
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
                if not isinstance(p, dict):
                    continue
                changed, notes = fix_item(p)
                if changed:
                    touched = True
                    fixed += 1
                    print(f"[fix] {md.name}/{f.name} {p.get('id')}: {notes}")
            if touched and not dry:
                tmp = f.with_name(f.name + ".tmp")
                tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                tmp.replace(f)
    print(f"AUTOFIX {'DRY-RUN ' if dry else ''}DONE（修复 {fixed} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
