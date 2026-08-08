import json
import time
from pathlib import Path

REPORT_ROOT = Path(__file__).resolve().parent.parent / "failure_reports"


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
        }
        (folder / "report.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[failure] 报告已导出: {folder}")
        return folder


_reporter = FailureReporter()
