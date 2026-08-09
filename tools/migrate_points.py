"""Bug 230/231/232：点位数据迁移（v1 → v2），事务保护。

流程：backup → migrate → verify → replace
  - 迁移前整库备份（migrate_backup/ 目录）
  - 每文件先写 tmp 并 verify（可加载+字段齐全）才 replace
  - 失败自动回滚（备份恢复）
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUIDES = ROOT / "knowledge" / "guides" / "maps"
POINTS_VERSION = 2

REQUIRED_FIELDS = ["id", "name", "type", "region", "x", "y",
                   "coordinate_type", "status", "confidence",
                   "resolution"]


def _verify(items):
    """迁移后校验：可加载 + 必需字段齐全。返回 (ok, [问题])。"""
    if not isinstance(items, list):
        return False, ["不是列表"]
    for p in items:
        if not isinstance(p, dict):
            return False, [f"非对象: {p!r}"]
        for f in REQUIRED_FIELDS:
            if f not in p:
                return False, [f"{p.get('id')} 缺 {f}"]
    return True, []


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
    backup_dir = GUIDES / "migrate_backup"
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
            if not touched:
                continue
            migrated += len(items)
            if dry:
                print(f"[migrate] {md.name}/{f.name}（{len(items)} 条 → v{POINTS_VERSION}）")
                continue
            # 事务：backup → write tmp → verify → replace
            rel = f.relative_to(GUIDES)
            # 审查 P1：备份带时间戳（原每次覆盖同一路径——上一轮备份丢失）
            import time as _t
            backup_target = backup_dir / rel.with_name(
                f"{rel.name}.{_t.strftime('%Y%m%d%H%M%S')}.bak")
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, backup_target)  # 231：迁移前备份
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            ok, problems = _verify(json.loads(tmp.read_text(encoding="utf-8")))
            if not ok:
                # 232：verify 失败 → 回滚（tmp 删除，原文件不动）
                tmp.unlink(missing_ok=True)
                print(f"[ROLLBACK] {md.name}/{f.name} 校验失败: {problems[:3]}")
                continue
            tmp.replace(f)
            print(f"[migrate] {md.name}/{f.name}（{len(items)} 条 → v{POINTS_VERSION}）")

    if not dry and migrated:
        (backup_dir / "migrate_log.json").write_text(
            json.dumps({"version": POINTS_VERSION,
                        "migrated": migrated,
                        "backup_dir": str(backup_dir)},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MIGRATE {'DRY-RUN ' if dry else ''}DONE（涉及 {migrated} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
