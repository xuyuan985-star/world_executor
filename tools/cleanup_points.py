"""低质量点位维护（Bug 169）：定期淘汰无效点位。

规则：
  1. status=pending_review 且 confidence<0.8（低可信未复核）
  2. 坐标超出 [0,1] 或缺失
  3. region 引用的区域文件已删除

用法：python tools/cleanup_points.py [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUIDES = ROOT / "knowledge" / "guides" / "maps"


def validate_point(p, area_ids):
    if not isinstance(p, dict):
        return "非对象条目"
    pid = p.get("id")
    if not pid:
        return "缺 id"
    for f in ("x", "y"):
        # 审查 P1：坐标缺失必须淘汰（docstring 规则 2：超出 [0,1] 或缺失）——
        # 原 continue 跳过使规则永不生效
        if f not in p or p[f] is None:
            return f"缺 {f} 坐标"
        try:
            v = float(p[f])
            if not (0.0 <= v <= 1.0):
                return f"{f}={v} 超出 [0,1]"
        except (TypeError, ValueError):
            return f"{f} 非数值"
    conf = p.get("confidence")
    if p.get("status") == "pending_review" and conf is not None:
        try:
            if float(conf) < 0.8:
                return f"低置信 {conf}"
        except (TypeError, ValueError):
            return "confidence 非数值"
    if p.get("region") and p["region"] not in area_ids:
        return f"区域不存在 {p['region']}"
    return None


def main():
    dry = "--dry-run" in sys.argv
    soft = "--soft" in sys.argv  # Bug 427：软删除（标记 deleted 而非移除）
    removed = 0
    for md in sorted(GUIDES.iterdir()):
        if not md.is_dir():
            continue
        area_ids = {a.stem for a in (md / "areas").glob("*.json")} \
            if (md / "areas").exists() else set()
        pdir = md / "points"
        if not pdir.exists():
            continue
        for f in pdir.glob("*.json"):
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(items, list):
                continue
            keep = []
            for p in items:
                reason = validate_point(p, area_ids)
                if reason:
                    removed += 1
                    if soft and isinstance(p, dict):
                        # Bug 427：软删除——保留数据，标记状态（可恢复/审计）
                        p["deleted"] = True
                        p["delete_reason"] = reason
                        keep.append(p)
                    else:
                        print(f"[drop] {md.name}/{f.name} {p.get('id')}: {reason}")
                else:
                    keep.append(p)
            if len(keep) != len(items) and not dry:
                tmp = f.with_name(f.name + ".tmp")
                tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                tmp.replace(f)
    print(f"CLEANUP {'DRY-RUN ' if dry else ''}DONE"
          f"（{'软删除' if soft else '移除'} {removed} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
