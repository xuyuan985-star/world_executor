"""GuidesView（重构版）：BasePage 框架 + Splitter + 业务化树 + 详情操作。"""
import json
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QSizePolicy, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

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
        self.set_status("选择区域查看点位")

        # 主体：Splitter（左侧树 / 右侧详情）
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["目标", "进度"])
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.itemClicked.connect(self._on_item)
        split.addWidget(self.tree)

        self.detail = CardWidget()
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(16, 16, 16, 16)
        dl.setSpacing(12)

        self.detail_title = StrongBodyLabel("选择区域")
        self.detail_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        dl.addWidget(self.detail_title)

        # 完成进度
        self.detail_progress = QProgressBar()
        self.detail_progress.setRange(0, 100)
        self.detail_progress.setValue(0)
        self.detail_progress.setTextVisible(True)
        self.detail_progress.setFormat("完成 %v%")
        dl.addWidget(self.detail_progress)

        # 统计行
        self.detail_stats = QLabel("0 / 0 完成")
        self.detail_stats.setStyleSheet("color: #7A90B0; font-size: 13px;")
        dl.addWidget(self.detail_stats)

        # 定位信息
        self.detail_loc = QLabel("")
        self.detail_loc.setWordWrap(True)
        self.detail_loc.setStyleSheet("color: #7A90B0; font-size: 12px;")
        dl.addWidget(self.detail_loc)

        # 点位明细
        self.detail_body = QLabel("点位明细将显示在这里")
        self.detail_body.setWordWrap(True)
        self.detail_body.setStyleSheet("color: #B0C4DE; font-size: 13px;")
        dl.addWidget(self.detail_body)
        dl.addStretch(1)

        # 操作区
        ops = QHBoxLayout()
        self.run_btn = QPushButton("执行此区域")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._on_run)
        self.mark_btn = QPushButton("标记完成")
        self.mark_btn.setEnabled(False)
        self.mark_btn.clicked.connect(self._on_mark_done)
        ops.addWidget(self.run_btn)
        ops.addWidget(self.mark_btn)
        ops.addStretch(1)
        dl.addLayout(ops)

        split.addWidget(self.detail)
        split.setStretchFactor(0, 2)   # 树 40%
        split.setStretchFactor(1, 3)   # 详情 60%
        self.tree.header().setStretchLastSection(True)
        self.tree.resizeColumnToContents(0)
        self.content_layout.addWidget(split, 1)

        self._maps = {}
        self._map_names = {}           # map_dir -> map_name
        self._selected = None
        self._point_status = {}        # point_id -> status
        self._region_points = {}       # (map, region) -> [point_id, ...]
        self._point_info = {}          # point_id -> {name, category, coord, ...}
        self.reload()

    def reload(self):
        # 保留用户已标记的完成状态（不随刷新丢失）
        saved_status = getattr(self, "_point_status", {})

        self.tree.clear()
        self._maps = {}
        self._map_names = {}
        self._region_points = {}
        self._point_info = {}
        self._point_status = dict(saved_status)

        # 重置详情区
        self.detail_title.setText("选择区域")
        self.detail_body.setText("点位明细将显示在这里")
        self.detail_loc.setText("")
        self._set_progress(0, 0)
        self.run_btn.setEnabled(False)
        self.mark_btn.setEnabled(False)

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
            map_name = map_doc.get("name", md.name)
            top = QTreeWidgetItem([map_name,
                                   f"{total} 个点位"])
            top.setData(0, Qt.UserRole, ("map", md.name, None))
            self.tree.addTopLevelItem(top)
            self._maps[md.name] = md
            self._map_names[md.name] = map_name
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
                rkey = (md.name, a.stem)
                self._region_points[rkey] = []
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
                        pid = pt.get("id")
                        leaf = QTreeWidgetItem([f"  {zh} {pt.get('name', pid)}",
                                                self._status_text(pid)])
                        leaf.setData(0, Qt.UserRole, ("point", md.name, pid))
                        child.addChild(leaf)
                        self._region_points[rkey].append(pid)
                        self._point_info[pid] = {
                            "name": pt.get("name", pid),
                            "category": zh,
                            "coord": pt.get("coord") or pt.get("position") or pt.get("location"),
                            "region": a.stem,
                            "map": md.name,
                        }
            top.setExpanded(True)
        self.tree.expandToDepth(1)

    def _status_text(self, pid):
        return "已完成" if self._point_status.get(pid) == "done" else "待执行"

    def _update_tree_status(self, pid=None):
        """同步叶子节点状态显示与区域统计。

        pid 为 None 时刷新全部叶子（用于区域级标记完成）。
        """
        it = Qt.UserRole
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            map_item = root.child(i)
            for j in range(map_item.childCount()):
                area_item = map_item.child(j)
                done = 0
                total = 0
                for k in range(area_item.childCount()):
                    leaf = area_item.child(k)
                    lkind, lmap, lpid = leaf.data(0, it)
                    total += 1
                    if self._point_status.get(lpid) == "done":
                        done += 1
                    if pid is None or lpid == pid:
                        leaf.setText(1, self._status_text(lpid))
                area_item.setText(1, f"{done}/{total}")

    def _on_item(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not isinstance(data, (tuple, list)) or len(data) != 3:
            return
        kind, mdir, key = data
        self._selected = (kind, mdir, key)
        md = self._maps.get(mdir)
        if md is None:
            return

        map_name = self._map_names.get(mdir, mdir)
        if kind == "map":
            self.detail_title.setText(map_name)
            self.detail_body.setText("选择区域查看点位")
            self.detail_loc.setText("")
            self._set_progress(0, 0)
            self.run_btn.setEnabled(False)
            self.mark_btn.setEnabled(False)

        elif kind == "area":
            lines = []
            pids = []
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
                        pid = pt.get("id")
                        pids.append(pid)
                        mark = "✓" if self._point_status.get(pid) == "done" else "□"
                        coord = pt.get("coord") or pt.get("position") or pt.get("location")
                        coord_txt = f"  坐标: {coord}" if coord else ""
                        lines.append(f"{mark} {zh} {pt.get('name', pid)}{coord_txt}")
            done = sum(1 for p in pids if self._point_status.get(p) == "done")
            self.detail_title.setText(f"区域: {item.text(0)}")
            self.detail_body.setText("\n".join(lines) or "（无点位）")
            self.detail_loc.setText(f"地图: {map_name} / 区域: {key}")
            self._set_progress(done, len(pids))
            self.run_btn.setEnabled(bool(lines))
            self.mark_btn.setEnabled(bool(pids))

        else:  # point
            info = self._point_info.get(key, {})
            coord = info.get("coord")
            coord_txt = f"坐标: {coord}" if coord else "暂无坐标"
            self.detail_title.setText(f"{info.get('category', '点位')} {info.get('name', key)}")
            self.detail_body.setText(f"状态: {self._status_text(key)}\n{coord_txt}")
            self.detail_loc.setText(f"地图: {map_name} / 区域: {info.get('region', '—')}")
            self._set_progress(1 if self._point_status.get(key) == "done" else 0, 1)
            self.run_btn.setEnabled(True)
            self.mark_btn.setEnabled(True)

    def _set_progress(self, done, total):
        if total <= 0:
            self.detail_progress.setValue(0)
            self.detail_stats.setText("0 / 0 完成")
            return
        pct = int(done * 100 / total)
        self.detail_progress.setValue(pct)
        self.detail_stats.setText(f"{done} / {total} 完成")

    def _on_run(self):
        kind, mdir, key = self._selected or (None, None, None)
        if kind == "area":
            self.set_status(f"已选择区域 {key} — 待接入执行", busy=True)
        elif kind == "point":
            self.set_status(f"已选择点位 {key} — 待接入执行", busy=True)

    def _on_mark_done(self):
        kind, mdir, key = self._selected or (None, None, None)
        if kind == "point":
            self._point_status[key] = "done"
            self._update_tree_status(key)
            self._on_item(self.tree.currentItem(), 0)
            self.set_status(f"点位 {key} 已标记完成", busy=False)
        elif kind == "area":
            rkey = (mdir, key)
            for pid in self._region_points.get(rkey, []):
                self._point_status[pid] = "done"
            self._update_tree_status(None)
            self._on_item(self.tree.currentItem(), 0)
            self.set_status(f"区域 {key} 已全标记完成", busy=False)
