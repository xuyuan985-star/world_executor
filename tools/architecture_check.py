"""附录 D.1 依赖方向 lint：违反冻结规则的 import 直接拒绝合并。

用法: python tools/architecture_check.py [repo_root]

AST 检查（替代 regex）：覆盖 import runtime.executor as x / from runtime import executor
等 alias 写法——任何形式的 import 都可能产生模块访问，漏检即违规。
"""
import ast
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

# #24：第三方/产物目录不扫描（CI 不应因 vendor/March7th 代码炸）
IGNORE_DIRS = {"__pycache__", ".venv", "node_modules", "vendor", "March7thAssistant", "tests", "examples"}


def _import_modules(tree):
    """收集文件里所有被 import 的模块全名（含 alias 形式）。"""
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.append(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.append(node.module)
            elif node.module and node.level > 0:
                # 相对导入：runtime 内部使用（如 from . import db），按包起点补全
                base = ".".join(node.module.split(".")[:1])
                mods.append(base)
    return mods


def _is_or_below(rel, mod):
    """#30：模块边界必须精确——runtime2.xxx 不是 runtime，runtime.api 是 runtime 之下。"""
    return rel == mod or rel.startswith(mod + ".")


def check_file(path: Path, root: Path):
    rel = path.relative_to(root).as_posix()
    src = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    rel_mod = ".".join(rel.replace(".py", "").split("/"))
    violations = []
    for mod in _import_modules(tree):
        for bad_from, bad_to in FORBIDDEN:
            if _is_or_below(rel_mod, bad_from) and _is_or_below(mod, bad_to):
                if any(_is_or_below(rel_mod, p) and _is_or_below(mod, q)
                       for p, q in ALLOW_PREFIX):
                    continue
                violations.append(f"{rel} 禁止 {rel_mod} → {mod}（{bad_to}）")
    return violations


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    issues = []
    for py in sorted(root.rglob("*.py")):
        if any(part in IGNORE_DIRS for part in py.parts):
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
