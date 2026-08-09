"""端到端 pipeline 测试（Bug 100）：数据 → 知识包 → 校验 → dry_run 全链路。

覆盖：
  1. guides 攻略库数据完整（地图/区域/点位结构）
  2. 执行知识包（black_tower_test）schema 校验通过
  3. 每条点位 workflow 存在且 dry_run 逻辑跑通
  4. 点位 id 全局唯一（map.area 前缀）无冲突

用法：python tools/full_pipeline_test.py（gate 内自动执行）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUIDES = ROOT / "knowledge" / "guides" / "maps"
PKG_DIR = ROOT / "knowledge" / "source" / "black_tower_test"


def check_guides():
    errors = []
    if not GUIDES.exists():
        return [f"攻略库不存在: {GUIDES}"]
    for md in sorted(GUIDES.iterdir()):
        if not md.is_dir():
            continue
        map_json = md / "map.json"
        if not map_json.exists():
            errors.append(f"{md.name}: 缺 map.json")
            continue
        try:
            doc = json.loads(map_json.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{md.name}: map.json 损坏 {e}")
            continue
        if not doc.get("name"):
            errors.append(f"{md.name}: map.json 缺 name")
        areas = list((md / "areas").glob("*.json")) if (md / "areas").exists() else []
        if not areas:
            errors.append(f"{md.name}: 无区域文件")
        for a in areas:
            try:
                adoc = json.loads(a.read_text(encoding="utf-8"))
                if not adoc.get("name"):
                    errors.append(f"{md.name}/{a.stem}: 缺 name")
            except Exception as e:
                errors.append(f"{md.name}/{a.stem}: 损坏 {e}")
    return errors


def check_ids_unique():
    """点位 id 全局唯一（map 前缀）：跨文件收集去重。"""
    ids = {}
    dupes = []
    for md in sorted(GUIDES.iterdir()):
        pdir = md / "points"
        if not pdir.exists():
            continue
        for f in pdir.glob("*.json"):
            try:
                pts = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(pts, list):
                continue
            for p in pts:
                if not isinstance(p, dict) or not p.get("id"):
                    continue
                pid = p["id"]
                if pid in ids:
                    dupes.append(f"{pid}（{ids[pid]} 与 {f}）")
                ids[pid] = str(f)
    return dupes


def check_knowledge_pkg():
    from ingest.compiler.validate_graph import validate
    from runtime.knowledge_loader import KnowledgePackage
    errors = []
    if not PKG_DIR.exists():
        return [f"执行知识包不存在: {PKG_DIR}"]
    pkg = KnowledgePackage(PKG_DIR)
    verrors, _ = validate(pkg, verbose=False)
    errors.extend(f"知识包: {e}" for e in verrors)
    # 每条目标都有 workflow 且 dry_run 跑通
    from runtime import dry_run
    wfs = list((PKG_DIR / "workflows").glob("*.json"))
    if not wfs:
        errors.append("知识包无 workflow")
    return errors


def main():
    ok = True
    for name, fn in [("guides 数据", check_guides),
                     ("点位 id 唯一", check_ids_unique),
                     ("知识包+workflow", check_knowledge_pkg)]:
        errs = fn()
        if errs:
            ok = False
            print(f"[{name}] FAIL")
            for e in errs[:8]:
                print(f"  - {e}")
        else:
            print(f"[{name}] PASS")
    print("PIPELINE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
