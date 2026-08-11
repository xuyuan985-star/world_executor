"""Bug 242：全库完整性扫描（validate_all）——扫描所有知识包 + 攻略库。

用法：python tools/validate_all.py [--report report.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.compiler.validate_graph import validate
from runtime.knowledge_loader import KnowledgePackage

GUIDES = ROOT / "knowledge" / "guides" / "maps"
PKG_DIRS = [d for d in (ROOT / "knowledge/source").iterdir() if d.is_dir()]


def scan():
    report = {"knowledge_packages": {}, "guides": {}, "ok": True}
    for pdir in sorted(PKG_DIRS):
        try:
            pkg = KnowledgePackage(pdir)
            errors, warnings = validate(pkg, verbose=False)
            report["knowledge_packages"][pdir.name] = {
                "status": "FAIL" if errors else "PASS",
                "errors": errors[:10], "warnings": warnings[:5],
                "environment": pkg.environment}
            if errors:
                report["ok"] = False
        except Exception as e:
            report["knowledge_packages"][pdir.name] = {
                "status": "ERROR", "errors": [f"{type(e).__name__}: {e}"]}
            report["ok"] = False
    if GUIDES.exists():
        for md in sorted(GUIDES.iterdir()):
            if not md.is_dir():
                continue
            area_files = list((md / "areas").glob("*.json")) \
                if (md / "areas").exists() else []
            point_files = list((md / "points").glob("*.json")) \
                if (md / "points").exists() else []
            problems = []
            if not (md / "map.json").exists():
                problems.append("缺 map.json")
            if not area_files:
                problems.append("无区域文件")
            for f in point_files:
                if f.name == "points_meta.json":
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        problems.append(f"{f.name}: 非列表")
                except Exception as e:
                    problems.append(f"{f.name}: 损坏 {type(e).__name__}")
            report["guides"][md.name] = {
                "status": "FAIL" if problems else "PASS",
                "areas": len(area_files), "point_files": len(point_files),
                "problems": problems[:10]}
            if problems:
                report["ok"] = False
    return report


def main():
    report = scan()
    print(f"== validate_all: {'PASS' if report['ok'] else 'FAIL'} ==")
    for name, info in report["knowledge_packages"].items():
        print(f"  [{info['status']}] 知识包 {name} (env={info.get('environment')})")
    for name, info in report["guides"].items():
        print(f"  [{info['status']}] 地图 {name} (areas={info['areas']}, points={info['point_files']})")
    if "--report" in sys.argv:
        i = sys.argv.index("--report")
        if i + 1 >= len(sys.argv):
            print("用法: python tools/validate_all.py --report <输出路径>")
            return 2
        out = Path(sys.argv[i + 1])
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"报告: {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
