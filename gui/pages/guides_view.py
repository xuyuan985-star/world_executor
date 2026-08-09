"""GuidesView（重构版）：BasePage 框架 + Splitter + 业务化树 + 详情操作。"""
import json
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from qfluentwidgets import CardWidget, StrongBodyLabel

from gui.pages.base_page import BasePage

GUIDES = Path(__file__).resolve().parent.parent.parent / "knowledge" / "guides" / "maps"

POINT_FILES = {
    "chests.json": "宝箱", "warptrotters.json": "扑满", "puzzles.json": "解密",
    "books.json": "书籍", "enemies.json": "强敌", "achievements.json": "成就",
    "quests.json": "任务", "shops.json": "商店", "anchors.json": "锚点",
}


class GuidesView(BasePage):
    """攻略体系：地图 → 区域 → 点位（业务化展示 + 可执行操作）。"""

    def __init__(self, parent=None):
        super().__init__("攻略体系", parent)

        # Header 状态：完成统计
        self.set_status("选择区域查看点位")

        # 主体：Splitter（左侧树 / 右侧详情，可拖动）
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["目标", "进度"])
        from PySide6.QtWidgets import QSizePolicy
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.itemClicked.connect(self._on_item)
        split.addWidget(self.tree)

        self.detail = CardWidget()
        dl = QVBoxLayout(self.detail)
        self.detail_title = StrongBodyLabel("选择区域")
        self.detail_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.detail_body = QLabel("点位明细将显示在这里")
        self.detail_body.setWordWrap(True)
        self.detail_body.setStyleSheet("color: #7A90B0;")
        dl.addWidget(self.detail_title)
        dl.addWidget(self.detail_body)
        # 操作区（Footer 级）
        ops = QHBoxLayout()
        self.run_btn = QPushButton("执行此区域")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._on_run)
        ops.addWidget(self.run_btn)
        ops.addStretch(1)
        dl.addLayout(ops)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 2)   # 树 40%
        split.setStretchFactor(1, 3)   # 详情 60%
        self.tree.header().setStretchLastSection(True)
        self.tree.resizeColumnToContents(0)
        self.content_layout.addWidget(split, 1)

        self._maps = {}
        self._selected = None
        self.reload()

    def reload(self):
        self.tree.clear()
        self._maps = {}
        if not GUIDES.exists():
            self.detail_body.setText("攻略库不存在，请先导入知识库")
            return
        for md in sorted(GUIDES.iterdir()):
            if not md.is_dir():
                continue
            try:
                map_doc = json.loads((md / "map.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            areas = sorted((md / "areas").glob("*.json"))
            # 区域 → 点位统计（完成数占位——待接入执行状态）
            region_stats = defaultdict(lambda: [0, 0])
            for f, _zh in POINT_FILES.items():
                pf = md / "points" / f
                if not pf.exists():
                    continue
                try:
                    pts = json.loads(pf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for pt in pts:
                    region_stats[pt.get("region", "?")][1] += 1
            total = sum(v[1] for v in region_stats.values())
            top = QTreeWidgetItem([map_doc.get("name", md.name),
                                   f"{total} 个点位"])
            top.setData(0, Qt.UserRole, ("map", md.name, None))
            self.tree.addTopLevelItem(top)
            self._maps[md.name] = md
            for a in areas:
                try:
                    adoc = json.loads(a.read_text(encoding="utf-8"))
                except Exception:
                    continue
                done, cnt = region_stats.get(a.stem, [0, 0])
                child = QTreeWidgetItem(
                    [f"{adoc.get('name', a.stem)}", f"{done}/{cnt}"])
                child.setData(0, Qt.UserRole, ("area", md.name, a.stem))
                top.addChild(child)
                for f, zh in POINT_FILES.items():
                    pf = md / "points" / f
                    if not pf.exists():
                        continue
                    try:
                        pts = json.loads(pf.read_text(encoding="utf-8"))
                    except Exception as e:
                        print(f"[guides] JSON 损坏 {pf}: {e}")
                        continue
                    for pt in pts:
                        if pt.get("region") != a.stem:
                            continue
                        leaf = QTreeWidgetItem([f"  {zh} {pt.get('name', pt['id'])}",
                                                "待执行"])
                        leaf.setData(0, Qt.UserRole, ("point", md.name, pt.get("id")))
                        child.addChild(leaf)
            top.setExpanded(True)
        self.tree.expandToDepth(1)

    def _on_item(self, item, _col):
        kind, mdir, key = item.data(0, Qt.UserRole)
        self._selected = (kind, mdir, key)
        if kind == "map":
            md = self._maps.get(mdir)
            if md is None:
                return
            self.detail_title.setText(mdir)
            self.detail_body.setText("选择区域查看点位")
            self.run_btn.setEnabled(False)
        elif kind == "area":
            md = self._maps.get(mdir)
            if md is None:
                return
            lines = []
            for f, zh in POINT_FILES.items():
                pf = md / "points" / f
                if not pf.exists():
                    continue
                try:
                    pts = json.loads(pf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for pt in pts:
                    if pt.get("region") == key:
                        lines.append(f"□ {zh} {pt.get('name', pt['id'])}")
            self.detail_title.setText(f"区域: {item.text(0)}")
            self.detail_body.setText("\n".join(lines) or "（无点位）")
            self.run_btn.setEnabled(bool(lines))
        else:
            md = self._maps.get(mdir)
            if md is None:
                return
            self.detail_title.setText("点位")
            self.detail_body.setText(item.text(0))
            self.run_btn.setEnabled(True)

    def _on_run(self):
        kind, mdir, key = self._selected or (None, None, None)
        if kind == "area":
            self.set_status(f"已选择区域 {key} — 待接入执行", busy=True)
        elif kind == "point":
            self.set_status(f"已选择点位 {key} — 待接入执行", busy=True)
