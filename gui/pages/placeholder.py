"""Placeholder 页面：全部接入 BasePage 统一框架。"""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from qfluentwidgets import BodyLabel, CardWidget, ComboBox, StrongBodyLabel

from gui.pages.base_page import BasePage, card_layout, card_title


def error_page(source, error):
    """Bug 53：页面构造失败兜底页（显示错误而非空白/崩溃）。"""
    return placeholder_page(f"{source} 初始化失败", f"错误: {error}")


def placeholder_page(title, note):
    """占位页：卡片置顶（无顶部 stretch 空洞）。"""
    page = BasePage(title)
    card = CardWidget()
    card_layout(card)
    label = BodyLabel(note)
    label.setStyleSheet("color: #7A90B0;")
    card_layout(card).addWidget(label)
    page.content_layout.addWidget(card)
    page.content_layout.addStretch(1)
    return page


class WorldGraphPage(BasePage):
    """世界图：地图级可视化（嵌入攻略体系视图，不重复页头）。"""

    def __init__(self, parent=None):
        super().__init__("世界图", parent)
        self.set_status("地图级执行视图")
        from gui.pages.guides_view import GuidesView
        self._view = GuidesView(self).set_embedded()
        self.content_layout.addWidget(self._view)


class ObservationPage(BasePage):
    """观察中心：游戏画面 + 事件流统计与诊断。"""

    def __init__(self, parent=None):
        super().__init__("观察中心", parent)
        self.set_status("点击[抓取画面]查看游戏实时画面")
        self._counts = {}

        # 游戏画面卡片（实时监测）
        frame_card = CardWidget()
        card_title(frame_card, "游戏画面")
        self.frame_label = QLabel("点击「抓取画面」获取当前帧")
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.frame_label.setMinimumHeight(200)
        self.frame_label.setStyleSheet(
            "background: #101826; border: 1px dashed #24405F; border-radius: 8px;"
            "color: #7A90B0;")
        card_layout(frame_card).addWidget(self.frame_label)
        cap_row = QHBoxLayout()
        self.capture_btn = QPushButton("抓取画面")
        self.capture_btn.clicked.connect(self._capture)
        cap_row.addWidget(self.capture_btn)
        cap_row.addStretch(1)
        card_layout(frame_card).addLayout(cap_row)
        self.content_layout.addWidget(frame_card, 1)

        # 统计卡片
        stats_card = CardWidget()
        card_title(stats_card, "事件统计")
        self._stats = BodyLabel("尚未开始任务 — 事件统计将显示在这里")
        self._stats.setStyleSheet("color: #7A90B0; font-size: 13px;")
        card_layout(stats_card).addWidget(self._stats)
        self.content_layout.addWidget(stats_card)

        # 时间线：真事件流（最近 50 条）
        timeline_card = CardWidget()
        card_title(timeline_card, "事件时间线")
        self.timeline = QListWidget()
        self.timeline.setMaximumHeight(220)
        self.timeline.setStyleSheet(
            "background: #101826; border: 1px solid #24405F; border-radius: 8px;"
            "color: #B0C4DE; font-size: 12px;")
        card_layout(timeline_card).addWidget(self.timeline)
        self.content_layout.addWidget(timeline_card)

        self._worker = None

    def _capture(self):
        """后台线程抓帧 → 主线程显示（Qt 跨线程安全链）。"""
        self.capture_btn.setEnabled(False)
        self.capture_btn.setText("抓取中…")

        class FrameWorker(QThread):
            done = Signal(object)   # QPixmap or None
            err = Signal(str)

            def run(self):
                try:
                    from runtime.drivers.march7th.vision import March7thVision
                    vision = March7thVision()
                    shot = vision.take_screenshot()
                    if shot is None:
                        self.done.emit(None)
                        return
                    img = shot[0]
                    from PySide6.QtGui import QPixmap
                    from PIL.ImageQt import ImageQt
                    pix = QPixmap.fromImage(ImageQt(img))
                    self.done.emit(pix)
                except Exception as e:
                    self.err.emit(f"{type(e).__name__}: {e}")

        self._worker = FrameWorker(self)
        self._worker.done.connect(self._on_frame)
        self._worker.err.connect(self._on_frame_err)
        self._worker.start()

    def _on_frame(self, pix):
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("抓取画面")
        if pix is None:
            self.frame_label.setText("未获取到画面（游戏未启动或截图失败）")
        else:
            self.frame_label.setPixmap(pix.scaled(
                self.frame_label.width(), self.frame_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_frame_err(self, msg):
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("抓取画面")
        self.frame_label.setText(f"截图失败: {msg}")

    def on_event(self, event):
        self._counts[event.type] = self._counts.get(event.type, 0) + 1
        total = sum(self._counts.values())
        top = "、".join(f"{k}×{v}" for k, v in
                        sorted(self._counts.items(), key=lambda x: -x[1])[:5])
        self._stats.setText(f"已接收 {total} 事件 | {top}")
        # 时间线追加（滚动条跟随最新）
        from PySide6.QtWidgets import QListWidgetItem
        ctx = event.context or {}
        detail = event.detail or ""
        item = QListWidgetItem(f"[{event.type}] {detail}" +
                               (f" ({ctx.get('status', '')})" if ctx.get("status") else ""))
        self.timeline.addItem(item)
        if self.timeline.count() > 50:
            self.timeline.takeItem(0)
        self.timeline.scrollToBottom()


class KnowledgePage(BasePage):
    """知识体系：攻略库管理入口（统计视图，与世界图执行视图区分）。"""

    def __init__(self, parent=None):
        super().__init__("知识体系", parent)
        self.set_status("攻略库统计与数据源")

        # 统计卡片
        self.stats_card = CardWidget()
        card_title(self.stats_card, "入库统计")
        self.stats_label = BodyLabel("正在扫描…")
        self.stats_label.setStyleSheet("color: #7A90B0; font-size: 13px;")
        card_layout(self.stats_card).addWidget(self.stats_label)
        self.content_layout.addWidget(self.stats_card)

        # 数据源明细
        self.source_card = CardWidget()
        card_title(self.source_card, "数据源文件")
        self.source_label = BodyLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet("color: #B0C4DE; font-size: 13px;")
        card_layout(self.source_card).addWidget(self.source_label)
        card_layout(self.source_card).addStretch(1)
        self.content_layout.addWidget(self.source_card, 1)

        # 刷新按钮
        refresh_btn = QPushButton("刷新统计")
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self._refresh)
        self.add_footer(refresh_btn)
        self.footer.layout().setDirection(QHBoxLayout.RightToLeft)

        self._refresh()

    def _refresh(self):
        from gui.pages.guides_view import GUIDES, POINT_FILES
        if not GUIDES.exists():
            self.stats_label.setText("攻略库不存在")
            self.source_label.setText("请先导入知识库")
            return

        map_count = 0
        area_count = 0
        point_count = 0
        lines = []
        for md in sorted(GUIDES.iterdir()):
            if not md.is_dir():
                continue
            map_count += 1
            areas = list((md / "areas").glob("*.json")) if (md / "areas").exists() else []
            area_count += len(areas)
            map_name = md.name
            try:
                doc = json.loads((md / "map.json").read_text(encoding="utf-8"))
                map_name = doc.get("name", md.name)
            except Exception:
                pass
            sub_lines = [f"地图: {map_name}"]
            for f, zh in POINT_FILES.items():
                pf = md / "points" / f
                if not pf.exists():
                    continue
                try:
                    pts = json.loads(pf.read_text(encoding="utf-8"))
                    point_count += len(pts)
                    sub_lines.append(f"  {zh}: {len(pts)} 条")
                except Exception:
                    sub_lines.append(f"  {zh}: 读取失败")
            lines.append("\n".join(sub_lines))

        self.stats_label.setText(
            f"地图 {map_count} 个 · 区域 {area_count} 个 · 点位 {point_count} 条")
        self.source_label.setText("\n\n".join(lines) or "暂无数据")


class VideoCard(CardWidget):
    """视频卡片：名称 + 大小 + 操作。"""

    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.setFixedHeight(90)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        info = QVBoxLayout()
        info.setSpacing(4)
        self.name_label = StrongBodyLabel(video_path.name)
        self.name_label.setStyleSheet("font-size: 13px;")
        # Bug 9：文件可能在扫描后被删/移动——stat 异常不崩卡片
        try:
            mb = video_path.stat().st_size // 1024 // 1024
        except (FileNotFoundError, OSError):
            mb = 0
        self.size_label = BodyLabel(f"{mb} MB")
        self.size_label.setStyleSheet("color: #7A90B0; font-size: 12px;")
        info.addWidget(self.name_label)
        info.addWidget(self.size_label)
        layout.addLayout(info)
        layout.addStretch(1)

        self.play_btn = QPushButton("播放")
        self.play_btn.setFixedWidth(64)
        self.play_btn.setProperty("video_path", str(video_path))
        self.play_btn.clicked.connect(self._play)
        layout.addWidget(self.play_btn)

        self.archive_btn = QPushButton("归档")
        self.archive_btn.setFixedWidth(80)
        self.archive_btn.setProperty("video_path", str(video_path))
        layout.addWidget(self.archive_btn)

    def _play(self):
        """系统默认播放器打开（os.startfile 支持视频文件）。"""
        import os
        p = self.play_btn.property("video_path")
        if p and os.path.exists(p):
            os.startfile(p)


class StudioPage(BasePage):
    """工作室：视频攻略卡片化列表 + 一键归档。"""

    def __init__(self, parent=None):
        super().__init__("视频攻略", parent)
        self.set_status("视频归档管理")
        self._videos = []

        # 统计行
        stats_card = CardWidget()
        stats_layout = QHBoxLayout(stats_card)
        stats_layout.setContentsMargins(16, 12, 16, 12)
        self.video_stats = BodyLabel("正在扫描视频…")
        self.video_stats.setStyleSheet("color: #7A90B0; font-size: 13px;")
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedWidth(80)
        self.refresh_btn.clicked.connect(self._refresh)
        stats_layout.addWidget(self.video_stats)
        stats_layout.addStretch(1)
        stats_layout.addWidget(self.refresh_btn)
        self.content_layout.addWidget(stats_card)

        # 卡片网格容器
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)
        self.content_layout.addWidget(self.cards_container, 1)

        self._refresh()

        self._worker = None

    class ArchiveWorker(QThread):
        log = Signal(str)
        done = Signal(bool, str)

        def __init__(self, video):
            super().__init__()
            self.video = video

        def run(self):
            import subprocess
            import sys
            from pathlib import Path
            root = Path(__file__).resolve().parent.parent.parent
            # Bug 10：subprocess 异常（python/路径问题）不吞——done 必须发出，
            # 否则按钮永久卡"归档中"
            try:
                r = subprocess.run(
                    [sys.executable, str(root / "ingest" / "archive_video.py"),
                     str(self.video), "--max-frames", "12"],
                    capture_output=True, text=True, cwd=str(root),
                    timeout=600)
            except Exception as e:
                self.done.emit(False, f"归档进程异常: {type(e).__name__}: {e}")
                return
            out = (r.stdout + r.stderr)
            for line in out.splitlines():
                self.log.emit(line)
            self.done.emit(r.returncode == 0, out[-300:])

    def _refresh(self):
        root = Path(__file__).resolve().parent.parent.parent
        dirs = [root / "ingest" / "raw" / "videos",
                root.parent / "攻略视频"]
        self._videos = []
        for d in dirs:
            if d.exists():
                self._videos.extend(sorted(d.glob("*.mp4")))

        # 清空旧卡片（保留尾部 stretch 语义——刷新后恰一个撑开项，不累积）
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        total_mb = 0
        for v in self._videos:
            try:
                total_mb += v.stat().st_size
            except (FileNotFoundError, OSError):
                continue
        total_mb //= 1024 * 1024
        self.video_stats.setText(
            f"共 {len(self._videos)} 个视频 · {total_mb}MB · 已处理 → 攻略存档")

        for v in self._videos:
            card = VideoCard(v)
            card.archive_btn.clicked.connect(self._make_archive_handler(v))
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)

    def _make_archive_handler(self, video_path):
        def _handler():
            self._archive(video_path)
        return _handler

    def _archive(self, video):
        self._worker = self.ArchiveWorker(video)
        self._worker.done.connect(self._on_done)
        # Bug 11：线程完成即回收（防旧线程对象残留）
        self._worker.finished.connect(self._worker.deleteLater)
        # 禁用所有归档按钮
        for i in range(self.cards_layout.count()):
            w = self.cards_layout.itemAt(i).widget()
            if isinstance(w, VideoCard):
                w.archive_btn.setEnabled(False)
                w.archive_btn.setText("归档中…")
        self._worker.start()

    def _on_done(self, ok, tail):
        for i in range(self.cards_layout.count()):
            w = self.cards_layout.itemAt(i).widget()
            if isinstance(w, VideoCard):
                w.archive_btn.setEnabled(True)
                w.archive_btn.setText("归档")
        QMessageBox.information(self, "归档结果",
                                "成功\n" if ok else "失败（见日志）\n" + tail[-200:])
        from gui.pages.guides_view import GuidesView
        for w in self.findChildren(GuidesView):
            w.reload()


class SettingsPage(BasePage):
    """设置页：可交互配置（默认执行模式保存到 QSettings）。"""

    def __init__(self, parent=None):
        super().__init__("设置", parent)
        self.set_status("执行模式与环境信息")

        card = CardWidget()
        cl = card_layout(card)

        # 默认执行模式
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("默认执行模式:"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["模拟执行", "真机执行"])
        row1.addWidget(self.mode_combo)
        row1.addStretch(1)
        cl.addLayout(row1)

        # 环境信息（只读）
        info = QLabel(self._env_info())
        info.setWordWrap(True)
        info.setStyleSheet("color: #7A90B0; font-size: 13px;")
        cl.addWidget(info)

        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)

        # 保存按钮：右下固定宽
        save_btn = QPushButton("保存设置")
        save_btn.setFixedWidth(130)
        save_btn.clicked.connect(self._save)
        self.add_footer(save_btn)
        # Footer 右对齐
        f = self.footer.layout()
        f.setDirection(QHBoxLayout.RightToLeft)

        self._load()

    @staticmethod
    def _env_info():
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        m7 = root.parent / "March7thAssistant"
        try:
            from config import settings
            model = settings.qwen_vlm_analyze_model() or "未配置"
        except Exception:
            model = "未配置"
        return (f"引擎路径: {m7}\n"
                f"VLM 模型: {model}\n"
                f"Python: {sys.version.split()[0]}")

    def _load(self):
        from PySide6.QtCore import QSettings
        s = QSettings("WorldExecutor", "Studio")
        mode = s.value("default_mode", "dry")
        self.mode_combo.setCurrentIndex(1 if mode == "real" else 0)

    def _save(self):
        from PySide6.QtCore import QSettings
        s = QSettings("WorldExecutor", "Studio")
        s.setValue("default_mode", "real" if self.mode_combo.currentIndex() == 1 else "dry")
        QMessageBox.information(self, "设置", "已保存（默认执行模式）")

    def default_mode(self):
        from PySide6.QtCore import QSettings
        s = QSettings("WorldExecutor", "Studio")
        return s.value("default_mode", "dry")
