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

# Part 2-2.5：动态导入禁止（importlib.import_module / __import__ 绕过静态依赖图）
DYNAMIC_IMPORT_CALLS = {"import_module", "__import__"}

# Part 2-2.8：危险调用禁止（直接代码执行/外壳注入面；subprocess.run 参数化
# 调用属可审计用途，只禁 shell=True 通道）
BANNED_CALLS = {"exec", "eval", "compile", "os.system", "os.popen",
                "subprocess.call"}
BANNED_KEYWORDS = {"shell=True"}

# 白名单调用点（经审计的合法用途）
BANNED_ALLOW = {
    "runtime.vision_quality",   # np.asarray 等 numpy 内部，无 exec
}


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
    # Part 2-2.5：动态导入（importlib.import_module / __import__）
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in DYNAMIC_IMPORT_CALLS:
                violations.append(f"{rel} 禁止动态导入: {node.func.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DYNAMIC_IMPORT_CALLS:
                violations.append(f"{rel} 禁止动态导入: {node.func.id}")
    # Part 2-2.8：危险调用（exec/eval/os.system/shell=True）
    if rel_mod not in BANNED_ALLOW:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = None
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = f"{node.func.value.id}.{node.func.attr}" \
                        if isinstance(node.func.value, ast.Name) else node.func.attr
                if fname in BANNED_CALLS:
                    violations.append(f"{rel} 禁止危险调用: {fname}")
            if isinstance(node, ast.keyword) and node.arg == "shell" \
                    and isinstance(node.value, ast.Constant) and node.value.value is True:
                violations.append(f"{rel} 禁止 shell=True")
    return violations


def find_cycles(root: Path):
    """#15：runtime 包内模块依赖环（A→B→A），DFS 检测并报告环路径。

    只扫 runtime 树（业务内核）；工具/入口不参与环判定。
    """
    runtime_dir = root / "runtime"
    if not runtime_dir.exists():
        return []
    graph = {}
    for py in sorted(runtime_dir.rglob("*.py")):
        if any(part in IGNORE_DIRS for part in py.parts):
            continue
        mod = ".".join(py.relative_to(root).as_posix().replace(".py", "").split("/"))
        src = py.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        deps = []
        for m in _import_modules(tree):
            if m == "runtime" or m.startswith("runtime."):
                deps.append(m)
        graph[mod] = deps

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {m: WHITE for m in graph}
    stack = []
    cycles = []

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for dep in graph.get(node, []):
            dep_mod = dep
            if dep_mod not in graph:
                continue
            if color[dep_mod] == GRAY:
                i = stack.index(dep_mod)
                cycles.append(stack[i:] + [dep_mod])
            elif color[dep_mod] == WHITE:
                dfs(dep_mod)
        stack.pop()
        color[node] = BLACK

    for m in graph:
        if color[m] == WHITE:
            dfs(m)
    return cycles


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    issues = []
    for py in sorted(root.rglob("*.py")):
        if any(part in IGNORE_DIRS for part in py.parts):
            continue
        issues += check_file(py, root)
    cycles = find_cycles(root)
    if issues:
        print("架构边界违规：")
        for i in issues:
            print(f"  [违规] {i}")
        sys.exit(1)
    if cycles:
        print("runtime 依赖环（#15）：")
        for c in cycles:
            print(f"  [环] {' -> '.join(c)}")
        sys.exit(1)
    print("[ok] 架构边界检查通过（无违规、无依赖环）")


if __name__ == "__main__":
    main()
