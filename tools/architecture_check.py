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

# 目标 3（架构冻结）：runtime 业务核心禁止感知物理输入/屏幕合成捕获。
# 豁免适配面：drivers/（March7th 适配）、input/（输入后端）、win_capture.py
# （窗口捕获适配）。ctypes/win32gui 不列禁——safety/health 系统探测与
# 窗口监控属合法用途（监控职责，非执行输入）。
FORBIDDEN_RUNTIME_IMPORTS = {"pyautogui", "mss", "pynput", "mouse", "keyboard"}

# Sprint A（目标3 补强）：runtime 核心禁止直接 import March7th 包（module.*）与
# 浏览器自动化（selenium）——runtime 只产 ActionIntent，适配细节在 drivers 层。
FORBIDDEN_EXTERNAL_PREFIXES = ("module.", "selenium", "March7th")

# 豁免模块（适配层，允许上述 import）
RUNTIME_ADAPTER_MODULES = {
    "runtime.drivers",
    "runtime.input",
    "runtime.win_capture",
}

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
                # BUG-03：`from runtime import executor` 实际访问 runtime.executor——
                # 只记 node.module（runtime）会漏掉 alias 目标，依赖环检测漏边
                for n in node.names:
                    if n.name == "*":
                        mods.append(node.module)
                    else:
                        mods.append(f"{node.module}.{n.name}")
            elif node.module and node.level > 0:
                # 相对导入：由调用方传入当前包前缀补全（3.2-1 修复：
                # from .step_executor import X → runtime.step_executor）
                for n in node.names:
                    if n.name == "*":
                        mods.append("." * node.level + node.module)
                    else:
                        mods.append(("." * node.level + node.module) + "." + n.name)
    return mods


def _is_or_below(rel, mod):
    """#30：模块边界必须精确——runtime2.xxx 不是 runtime，runtime.api 是 runtime 之下。"""
    return rel == mod or rel.startswith(mod + ".")


def _resolve_relative(mod, file_path, root):
    """#20-3.2：相对导入还原为绝对模块名。

    runtime/a.py 里 `from .step_executor import X`（level=1, module="step_executor"）
    → runtime.step_executor。按文件所在包推导。
    """
    if not isinstance(mod, str) or not mod.startswith("."):
        return mod
    level = len(mod) - len(mod.lstrip("."))
    suffix = mod[level:]
    parts = file_path.relative_to(root).as_posix().replace(".py", "").split("/")
    base = parts[:-level] if level <= len(parts) else parts[:0]
    return ".".join(base + (suffix.split(".") if suffix else []))


def _resolve_imports(tree, file_path, root):
    mods = _import_modules(tree)
    return [(_resolve_relative(m, file_path, root) if m.startswith(".") else m)
            for m in mods]


def check_file(path: Path, root: Path):
    rel = path.relative_to(root).as_posix()
    src = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    rel_mod = ".".join(rel.replace(".py", "").split("/"))
    violations = []
    # 目标 3：runtime 业务核心禁止 pyautogui/mss（物理输入不泄漏进核心）
    is_runtime = _is_or_below(rel_mod, "runtime")
    is_adapter = any(_is_or_below(rel_mod, a) for a in RUNTIME_ADAPTER_MODULES)
    if is_runtime and not is_adapter:
        for mod in _resolve_imports(tree, path, root):
            top = mod.split(".")[0]
            if top in FORBIDDEN_RUNTIME_IMPORTS or mod in FORBIDDEN_RUNTIME_IMPORTS:
                violations.append(
                    f"{rel} 禁止 {rel_mod} → {mod}（runtime 核心不得感知物理输入/屏幕捕获）")
            if any(mod.startswith(p) for p in FORBIDDEN_EXTERNAL_PREFIXES):
                violations.append(
                    f"{rel} 禁止 {rel_mod} → {mod}（runtime 核心不得直连外部适配层/浏览器自动化）")
    for mod in _resolve_imports(tree, path, root):
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
        for m in _resolve_imports(tree, py, root):
            if m == "runtime" or m.startswith("runtime."):
                deps.append(m)
        graph[mod] = deps

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {m: WHITE for m in graph}
    stack = []
    cycles = []

    def nearest(dep):
        """#20-3.2：依赖模块不在图中时按最长前缀归并（runtime.b.sub → runtime.b）。"""
        if dep in graph:
            return dep
        cands = [m for m in graph if dep.startswith(m + ".")]
        return max(cands, key=len) if cands else dep

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for dep in graph.get(node, []):
            dep_mod = nearest(dep)
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
    import argparse
    import json
    parser = argparse.ArgumentParser(description="架构与安全 lint")
    parser.add_argument("root", nargs="?", default=None,
                        help="仓库根目录（默认脚本上级）")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON（CI 友好）")
    args = parser.parse_args()
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    issues = []
    for py in sorted(root.rglob("*.py")):
        if any(part in IGNORE_DIRS for part in py.parts):
            continue
        issues += check_file(py, root)
    cycles = find_cycles(root)
    if args.json:
        print(json.dumps({"ok": not issues and not cycles,
                          "violations": issues,
                          "cycles": [" -> ".join(c) for c in cycles]},
                         ensure_ascii=False, indent=2))
        sys.exit(0 if not issues and not cycles else 1)
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
