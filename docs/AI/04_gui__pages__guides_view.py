# gui/pages/guides_view.py

```python
"""攻略体系视图（GUI 联动：knowledge/guides 数据 → 树）。

地图 → 区域 → 点位统计；点击区域显示该区域点位明细。
"""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from qfluentwidgets import CardWidget, StrongBodyLabel

GUIDES = Path(__file__).resolve().parent.parent.parent / "knowledge" / "guides" / "maps"

POINT_FILES = {
    "chests.json": "宝箱", "warptrotters.json": "扑满", "puzzles.json": "解密",
    "books.json": "书籍", "enemies.json": "强敌", "achievements.json": "成就",
    "quests.json": "任务", "shops.json": "商店", "anchors.json": "锚点",
}


class GuidesView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = StrongBodyLabel("攻略体系（按大地图）")
        layout.addWidget(title)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["地图 / 区域", "点位"])
        self.tree.itemClicked.connect(self._on_item)
        split.addWidget(self.tree)

        self.detail = CardWidget()
        dl = QVBoxLayout(self.detail)
        self.detail_title = StrongBodyLabel("选择地图/区域")
        self.detail_body = QLabel("点位明细将显示在这里")
        self.detail_body.setWordWrap(True)
        self.detail_body.setStyleSheet("color: #7A90B0;")
        dl.addWidget(self.detail_title)
        dl.addWidget(self.detail_body)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split)

        self._maps = {}
        self.reload()

    def reload(self):
        self.tree.clear()
        self._maps = {}
        if not GUIDES.exists():
            self.detail_body.setText("knowledge/guides 不存在")
            return
        for md in sorted(GUIDES.iterdir()):
            if not md.is_dir():
                continue
            try:
                map_doc = json.loads((md / "map.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            areas = sorted((md / "areas").glob("*.json"))
            points = self._point_stats(md)
            top = QTreeWidgetItem([f"{map_doc.get('name', md.name)}",
                                   f"{points} 点 / {len(areas)} 区"])
            top.setData(0, Qt.UserRole, ("map", md.name, None))
            self.tree.addTopLevelItem(top)
            self._maps[md.name] = md
            for a in areas:
                try:
                    adoc = json.loads(a.read_text(encoding="utf-8"))
                except Exception:
                    continue
                pcount = 0
                for f, _ in POINT_FILES.items():
                    pf = md / "points" / f
                    if not pf.exists():
                        continue
                    try:
                        pts = json.loads(pf.read_text(encoding="utf-8"))
                    except Exception:
                        pts = []
                    pcount += sum(1 for pt in pts
                                  if pt.get("region") == adoc["id"])
                child = QTreeWidgetItem([adoc.get("name", a.stem), str(pcount)])
                child.setData(0, Qt.UserRole, ("area", md.name, a.stem))
                top.addChild(child)
            top.setExpanded(True)

    @staticmethod
    def _point_stats(md):
        total = 0
        for f in (md / "points").glob("*.json"):
            try:
                total += len(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return total

    def _on_item(self, item, _col):
        kind, mdir, area = item.data(0, Qt.UserRole)
        if kind == "map":
            md = self._maps.get(mdir)
            if md is None:
                return
            self.detail_title.setText(mdir)
            self.detail_body.setText(f"区域 {len(list((md/'areas').glob('*.json')))} 个；"
                                     f"点位 {self._point_stats(md)} 条")
        elif kind == "area":
            md = self._maps.get(mdir)
            if md is None:
                return
            lines = []
            for f, zh in POINT_FILES.items():
                p = md / "points" / f
                if not p.exists():
                    continue
                try:
                    pts = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for pt in pts:
                    if pt.get("region") == area:
                        lines.append(f"· [{zh}] {pt.get('name', pt['id'])}"
                                     f" ({pt.get('tier', '-')})")
            self.detail_title.setText(f"{area} 点位明细")
            self.detail_body.setText("\n".join(lines) or "（无点位）")

```
