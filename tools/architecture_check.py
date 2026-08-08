"""附录 D.1 依赖方向 lint：违反冻结规则的 import 直接拒绝合并。

用法: python tools/architecture_check.py [repo_root]
"""
import re
import sys
from pathlib import Path

FORBIDDEN = [
    ("gui", "runtime.step_executor"),
    ("gui", "runtime.state_machine"),
    ("gui", "runtime.events.schema"),
    ("gui", "runtime.dry_run"),
    ("gui", "runtime.observers"),
    ("gui", "runtime.db"),
    ("runtime.observers", "runtime.decision"),
    ("runtime.observers", "runtime.step_executor"),
    ("runtime.observers", "runtime.executor"),
    ("runtime.decision", "runtime.step_executor"),
    ("runtime.step_executor", "ingest.compiler"),
    ("runtime", "gui"),
]

ALLOW_PREFIX = [
    ("gui", "runtime.api"),
    ("runtime", "runtime.api"),
]


def check_file(path: Path, root: Path):
    rel = path.relative_to(root).as_posix()
    src = path.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r"^(import|from)\s+", src, re.M):
        return []
    rel_mod = ".".join(rel.replace(".py", "").split("/"))
    violations = []
    for imp in re.finditer(r"^\s*(?:import|from)\s+([\w\.]+)", src, re.M):
        mod = imp.group(1)
        for bad_from, bad_to in FORBIDDEN:
            if rel_mod.startswith(bad_from) and (mod == bad_to or mod.startswith(bad_to + ".")):
                if any(rel_mod.startswith(p) and (mod == q or mod.startswith(q + ".")) for p, q in ALLOW_PREFIX):
                    continue
                violations.append(f"{rel}:{src.count(chr(10), 0, imp.start()) + 1} 禁止 {rel_mod} → {mod}（{bad_to}）")
    return violations


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    issues = []
    for py in sorted(root.rglob("*.py")):
        if any(part in ("__pycache__", ".venv", "node_modules") for part in py.parts):
            continue
        issues += check_file(py, root)
    if issues:
        print("架构边界违规：")
        for i in issues:
            print(f"  [违规] {i}")
        sys.exit(1)
    print("[ok] 架构边界检查通过")


if __name__ == "__main__":
    main()
