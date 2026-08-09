from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from qfluentwidgets import BodyLabel, CardWidget, StrongBodyLabel


def card_layout(card):
    if card.layout() is None:
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
    return card.layout()


def card_title(card, text):
    label = StrongBodyLabel(text)
    label.setStyleSheet("font-size: 13px; letter-spacing: 1px;")
    card_layout(card).insertWidget(0, label)
    return label


def error_page(source, error):
    """Bug 53：页面构造失败兜底页（显示错误而非空白/崩溃）。"""
    return placeholder_page(f"{source} 初始化失败", f"错误: {error}")


def placeholder_page(title, note):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addStretch(1)
    card = CardWidget()
    card_title(card, title)
    label = BodyLabel(note)
    label.setStyleSheet("color: #7A90B0;")
    card_layout(card).addWidget(label)
    layout.addWidget(card)
    layout.addStretch(1)
    return page


class WorldGraphPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # GUI 联动：世界图 = 攻略体系地图层级
        from gui.pages.guides_view import GuidesView
        layout.addWidget(GuidesView(self))


class ObservationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = placeholder_page(
            "观测 Observation",
            "GUI-M0.3: state_observation 时间线 + fail/repair 审计 + Replay")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)


class KnowledgePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # GUI 联动：攻略体系（knowledge/guides 地图→区域→点位）
        from gui.pages.guides_view import GuidesView
        layout.addWidget(GuidesView(self))


class StudioPage(QWidget):
    """工作室：视频列表 + 一键归档（ingest/archive_video.py 链路）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QThread, Signal
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = StrongBodyLabel("视频攻略归档")
        layout.addWidget(title)

        self.video_list = QListWidget()
        layout.addWidget(self.video_list)

        row = QHBoxLayout()
        self.archive_btn = QPushButton("归档选中视频")
        self.archive_btn.clicked.connect(self._archive)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh)
        row.addWidget(self.archive_btn)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._videos = []
        self._refresh()

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
                r = subprocess.run(
                    [sys.executable, str(root / "ingest" / "archive_video.py"),
                     str(self.video), "--max-frames", "12"],
                    capture_output=True, text=True, cwd=str(root))
                out = (r.stdout + r.stderr)
                for line in out.splitlines():
                    self.log.emit(line)
                self.done.emit(r.returncode == 0, out[-300:])

        self._worker = None
        self._worker_cls = ArchiveWorker

    def _refresh(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        dirs = [root / "ingest" / "raw" / "videos",
                root.parent / "攻略视频"]  # 高清视频目录（Open Code 根）
        self._videos = []
        for d in dirs:
            if d.exists():
                self._videos.extend(sorted(d.glob("*.mp4")))
        self.video_list.clear()
        for v in self._videos:
            QListWidgetItem(f"{v.name}  ({v.stat().st_size//1024//1024}MB)",
                            self.video_list)

    def _archive(self):
        item = self.video_list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "先选择一个视频")
            return
        idx = self.video_list.row(item)
        video = self._videos[idx]
        self.archive_btn.setEnabled(False)
        self.archive_btn.setText("归档中…")
        self._worker = self._worker_cls(video)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, tail):
        self.archive_btn.setEnabled(True)
        self.archive_btn.setText("归档选中视频")
        QMessageBox.information(self, "归档结果",
                                "成功\n" if ok else "失败（见日志）\n" + tail[-200:])
        from gui.pages.guides_view import GuidesView
        for w in self.findChildren(GuidesView):
            w.reload()


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = placeholder_page(
            "设置 Settings",
            "GUI-M0.4: 引擎路径 / VLM 模型 / 界面")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)
