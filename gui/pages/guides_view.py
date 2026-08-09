"""GuidesView（重构）：左侧=大地图列表，右侧=选中地图的区域卡片（点位合并）。"""
import json
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from qfluentwidgets import CardWidget, StrongBodyLabel

from gui.pages.base_page import BasePage, card_title

GUIDES = Path(__file__).resolve().parent.parent.parent / "knowledge" / "guides" / "maps"

POINT_FILES = {
    "chests.json": "宝箱", "warptrotters.json": "扑满", "puzzles.json": "解密",
    "books.json": "书籍", "enemies.json": "强敌", "achievements.json": "成就",
    "quests.json": "任务", "shops.json": "商店", "anchors.json": "锚点",
}


class GuidesView(BasePage):
    """攻略体系：左侧大地图 → 右侧区域卡片（点位合并展示，不看细节）。"""

    def __init__(self, parent=None):
        super().__init__("攻略体系", parent)
        self.set_status("选择大地图查看区域")

        split = QSplitter(Qt.Horizontal)
        # 左侧：大地图列表（只到地图层）——35/65 比例，不固定宽（防长名省略号）
        self.map_list = QListWidget()
        self.map_list.setMinimumWidth(180)
        self.map_list.currentItemChanged.connect(self._on_map_selected)
        split.addWidget(self.map_list)

        # 右侧：区域卡片容器
        self.region_box = QWidget()
        self.region_layout = QVBoxLayout(self.region_box)
        self.region_layout.setContentsMargins(0, 0, 0, 0)
        self.region_layout.setSpacing(12)
        self.empty_label = QLabel("选择左侧大地图查看区域")
        self.empty_label.setStyleSheet("color: #7A90B0;")
        self.region_layout.addWidget(self.empty_label)
        self.region_layout.addStretch(1)
        split.addWidget(self.region_box)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([350, 650])
        self.content_layout.addWidget(split, 1)

        self._maps = {}        # map_dir -> {map_name, regions: {region_id: {name, points}}}
        self.reload()

    def reload(self):
        # Bug 304：刷新防抖（高频触发合并为一次重载）
        from PySide6.QtCore import QTimer
        if getattr(self, "_reload_timer", None) is None:
            self._reload_timer = QTimer(self)
            self._reload_timer.setSingleShot(True)
            self._reload_timer.setInterval(300)
            self._reload_timer.timeout.connect(self._do_reload)
        self._reload_timer.start()

    def _do_reload(self):
        self.map_list.clear()
        self._maps = {}
        if not GUIDES.exists():
            self.empty_label.setText("攻略库不存在，请先导入知识库")
            return
        for md in sorted(GUIDES.iterdir()):
            if not md.is_dir():
                continue
            try:
                map_doc = json.loads((md / "map.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            # 区域 → 点位类型计数（合并展示）
            region_pts = defaultdict(lambda: defaultdict(int))
            for f, zh in POINT_FILES.items():
                pf = md / "points" / f
                if not pf.exists():
                    continue
                try:
                    pts = json.loads(pf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for pt in pts:
                    region_pts[pt.get("region", "?")][zh] += 1
            regions = {}
            for a in (md / "areas").glob("*.json"):
                try:
                    adoc = json.loads(a.read_text(encoding="utf-8"))
                except Exception:
                    continue
                regions[a.stem] = {"name": adoc.get("name", a.stem),
                                   "points": dict(region_pts.get(a.stem, {}))}
            total = sum(sum(v.values()) for v in region_pts.values())
            self._maps[md.name] = {"map_name": map_doc.get("name", md.name),
                                   "regions": regions}
            item = QListWidgetItem(f"{map_doc.get('name', md.name)}  ({total})")
            item.setData(Qt.UserRole, md.name)
            self.map_list.addItem(item)
        if self.map_list.count():
            self.map_list.setCurrentRow(0)

    def _on_map_selected(self, cur, _prev):
        # 清空区域容器
        while self.region_layout.count():
            it = self.region_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if cur is None:
            return
        mdir = cur.data(Qt.UserRole)
        info = self._maps.get(mdir)
        if info is None:
            return
        self.set_status(f"{info['map_name']} — 选择区域开始执行")
        if not info["regions"]:
            self.empty_label = QLabel("该地图暂无区域数据")
            self.empty_label.setStyleSheet("color: #7A90B0;")
            self.region_layout.addWidget(self.empty_label)
            self.region_layout.addStretch(1)
            return
        for rid, rinfo in sorted(info["regions"].items()):
            card = CardWidget()
            card_title(card, rinfo["name"])
            pts = rinfo["points"]
            desc = "、".join(f"{zh}×{n}" for zh, n in pts.items()) or "无点位"
            body = QLabel(f"{desc}")
            body.setStyleSheet("color: #7A90B0; font-size: 13px;")
            row = QHBoxLayout()
            row.addWidget(body)
            row.addStretch(1)
            btn = QPushButton("执行此区域")
            btn.clicked.connect(lambda _=False, r=rid, m=mdir:
                                self._on_run(m, r))
            row.addWidget(btn)
            from gui.pages.placeholder import card_layout
            card_layout(card).addLayout(row)
            self.region_layout.addWidget(card)
        self.region_layout.addStretch(1)

    def _on_run(self, mdir, region):
        self.set_status(f"已选择 {mdir}/{region} — 执行接入中", busy=True)
