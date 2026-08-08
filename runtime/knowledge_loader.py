import json
from pathlib import Path


class KnowledgePackage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta = self._load("package.json") or {}
        self.rooms = self._load("rooms.json")
        self.portals = self._load("portals.json") or []
        self.landmarks = self._load("landmarks.json") or []
        self.chests = self._load("chests.json") or []
        self.templates_dir = self.root / "templates"
        self.workflows_dir = self.root / "workflows"

    def _load(self, name):
        p = self.root / name
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def workflow(self, target_id):
        p = self.workflows_dir / f"{target_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def spawn_room(self):
        return self.rooms["spawn_room"] if self.rooms else None

    def room_ids(self):
        return {r["id"] for r in self.rooms["rooms"]} if self.rooms else set()

    def chest(self, chest_id):
        for c in self.chests or []:
            if c["id"] == chest_id:
                return c
        return None

    def portal(self, portal_id):
        for p in self.portals or []:
            if p["id"] == portal_id:
                return p
        return None

    def template_exists(self, name):
        return (self.templates_dir / name).exists()
