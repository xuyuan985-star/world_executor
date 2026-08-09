# runtime/capabilities.py

```python
import yaml
from pathlib import Path

DEFAULT_CAPABILITIES = {
    "runtime_version": "0.1",
    "capabilities": {
        "room_detect": {"status": "mock"},
        "portal_transition": {"status": "mock"},
        "visual_move": {"status": "experimental"},
        "combat": {"status": "manual"},
        "puzzle": {"status": "disabled"},
        "home_return": {"status": "not_implemented"},
        "ocr": {"status": "ready"},
        "template_match": {"status": "ready"},
        "vlm_vision": {"status": "ready"},
    },
}


class CapabilityRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(__file__).parent.parent / "runtime" / "capabilities.yaml"
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            merged = DEFAULT_CAPABILITIES.copy()
            merged.update(loaded or {})
            merged.setdefault("capabilities", {}).update(DEFAULT_CAPABILITIES["capabilities"])
            return merged
        return DEFAULT_CAPABILITIES.copy()

    def status(self, capability):
        return self.data["capabilities"].get(capability, {}).get("status", "disabled")

    def is_ready(self, capability):
        return self.status(capability) in ("ready", "experimental")

    def check_requirements(self, requires, knowledge_id="unknown"):
        missing = [c for c in requires if not self.is_ready(c)]
        if missing:
            raise CapabilityError(
                f"knowledge[{knowledge_id}] requires {missing}, "
                f"runtime capabilities insufficient — abort before execution"
            )
        return True

    def summary(self):
        return {k: v["status"] for k, v in self.data["capabilities"].items()}


class CapabilityError(Exception):
    pass

```
