"""重新生成 docs/全部源代码.md——把仓库所有 .py 同步进文档（docs 目录除外）。"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".venv", "__pycache__", "docs", "AI"}
EXCLUDE_NAMES = {"gen_source_doc.py"}
OUT = ROOT / "docs" / "全部源代码.md"


def main():
    files = sorted(
        p for p in ROOT.rglob("*.py")
        if not any(part in EXCLUDE_DIRS for part in p.relative_to(ROOT).parts)
        and p.name not in EXCLUDE_NAMES
    )
    lines = [f"# WorldExecutor 全部源代码（自动生成）",
             f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M}—— 共 {len(files)} 个 .py 文件（docs 目录除外）",
             ""]
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        lines += [f"## {rel}", "", "```python",
                  f.read_text(encoding="utf-8").rstrip(), "```", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {OUT}（{len(files)} 个文件）")


if __name__ == "__main__":
    sys.exit(main())
