# runtime/failure_report.py

```python
import json
import platform
import time
from pathlib import Path

REPORT_ROOT = Path(__file__).resolve().parent.parent / "failure_reports"


def environment_snapshot():
    """环境快照（复现依据）：OS/DPI/Python/git commit。

    game_version 由调用方（KnowledgePackage）经 context 传入。
    """
    snap = {
        "windows_version": platform.platform(),
        "python_version": platform.python_version(),
        "git_commit": None,
        "dpi": None,
    }
    try:
        import subprocess
        snap["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parent.parent),
            stderr=subprocess.DEVNULL, text=True).strip() or None
    except Exception:
        pass
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            snap["dpi"] = dpi
        finally:
            user32.ReleaseDC(0, hdc)
    except Exception:
        pass
    return snap


class FailureReporter:
    def __init__(self, root=None):
        self.root = Path(root) if root else REPORT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def report(self, tag, screenshot_path=None, context=None, vlm_outputs=None, detail=None):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        folder = self.root / f"{stamp}_{tag}"
        folder.mkdir(parents=True, exist_ok=True)

        if screenshot_path and Path(screenshot_path).exists():
            import shutil
            shutil.copy2(screenshot_path, folder / Path(screenshot_path).name)

        doc = {
            "time": time.time(),
            "tag": tag,
            "detail": detail,
            "context": context or {},
            "vlm_outputs": vlm_outputs or {},
            "screenshot": Path(screenshot_path).name if screenshot_path else None,
            "environment": environment_snapshot(),  # 复现依据（git commit/DPI/OS）
        }
        # Part 2-2.6：脱敏（用户名路径 → C:\Users\<USER>\）
        from security.quarantine import sanitize_mapping
        doc["context"] = sanitize_mapping(doc["context"])
        doc["vlm_outputs"] = sanitize_mapping(doc["vlm_outputs"])
        doc["detail"] = sanitize_mapping(doc["detail"])
        (folder / "report.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "environment.json").write_text(
            json.dumps(doc["environment"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[failure] 报告已导出: {folder}")
        return folder


_reporter = FailureReporter()

```
