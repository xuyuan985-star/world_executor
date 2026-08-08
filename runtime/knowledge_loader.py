import hashlib
import json
import logging
from pathlib import Path

# #37：知识包结构版本——不匹配时拒绝加载（防止旧包以错误语义运行）
KNOWLEDGE_SCHEMA_VERSION = 1

# S11：运行器预期的游戏版本（知识包显式声明不同版本时告警，不拒绝——
# 游戏更新 UI 变化是渐变过程，版本声明用于人工判断而非硬阻断）
EXPECTED_GAME_VERSION = "2.x"

log = logging.getLogger("runtime.knowledge")


class KnowledgePackage:
    def __init__(self, root: Path, strict_schema=True):
        self.root = Path(root)
        self.meta = self._load("package.json") or {}
        if strict_schema:
            self._check_schema_version()
        self.rooms = self._load("rooms.json")
        self.portals = self._load("portals.json") or []
        self.landmarks = self._load("landmarks.json") or []
        self.chests = self._load("chests.json") or []
        self.templates_dir = self.root / "templates"
        self.workflows_dir = self.root / "workflows"
        # #28：启动即冻结——workflow 缓存 + 内容 hash，运行中改文件不影响执行链
        self._workflow_cache = {}
        self._package_hash = None

    def package_hash(self):
        """#28：知识包内容指纹（json 数据 + workflows），mission 事件携带。"""
        if self._package_hash is not None:
            return self._package_hash
        h = hashlib.sha256()
        for name in ("package.json", "rooms.json", "portals.json",
                     "landmarks.json", "chests.json"):
            p = self.root / name
            if p.exists():
                h.update(name.encode())
                h.update(p.read_bytes())
        for p in sorted(self.workflows_dir.glob("*.json")):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        self._package_hash = h.hexdigest()[:12]
        return self._package_hash

    def _check_schema_version(self):
        """#37：schema_version 不匹配 → 拒绝加载并告警（fail-fast）。"""
        ver = self.meta.get("schema_version")
        if ver is None:
            log.warning("知识包 %s 缺 schema_version，按 v%d 解析", self.root.name,
                        KNOWLEDGE_SCHEMA_VERSION)
        elif ver != KNOWLEDGE_SCHEMA_VERSION:
            raise ValueError(
                f"知识包 {self.root.name} schema_version={ver} 不匹配运行器 v{KNOWLEDGE_SCHEMA_VERSION}，"
                f"拒绝加载（更新知识包或运行器）")
        # S11：游戏版本声明不一致 → 告警（游戏 UI 变更时旧模板会失效，留人工判断）
        gv = self.meta.get("game_version")
        if gv and gv != EXPECTED_GAME_VERSION:
            log.warning("知识包 %s 声明 game_version=%s，运行器预期 %s——模板可能过期",
                        self.root.name, gv, EXPECTED_GAME_VERSION)

    def _load(self, name):
        p = self.root / name
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def workflow(self, target_id):
        # #28：缓存冻结——执行链不感知运行期文件修改
        if target_id in self._workflow_cache:
            return self._workflow_cache[target_id]
        p = self.workflows_dir / f"{target_id}.json"
        if not p.exists():
            return None
        wf = json.loads(p.read_text(encoding="utf-8"))
        self._workflow_cache[target_id] = wf
        return wf

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

    def entity_templates(self):
        """实体→模板映射：扫描 workflows/*.json 的 interact 步骤，
        并合并 portals/landmarks 的 trigger 模板。
        entity_id（世界实体）→ 模板文件名（driver/executor 层解析用）。"""
        mapping = {}
        if self.workflows_dir.exists():
            for p in sorted(self.workflows_dir.glob("*.json")):
                try:
                    wf = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                tid = wf.get("target_id")
                for step in wf.get("steps", []):
                    if step.get("type") == "interact" and step.get("template"):
                        mapping[tid] = step["template"]
                        break
        for item in (self.portals or []) + (self.landmarks or []):
            trig = item.get("trigger") or {}
            tmpl = trig.get("template") or item.get("template")
            if item.get("id") and tmpl:
                mapping.setdefault(item["id"], tmpl)
        return mapping
