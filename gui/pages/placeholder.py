"""Placeholder 页面：全部接入 BasePage 统一框架。"""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from qfluentwidgets import BodyLabel, CardWidget, ComboBox, StrongBodyLabel

from gui.pages.base_page import BasePage, card_layout, card_title


class TaskCenterPage(BasePage):
    """任务中心：March7th 任务模块全量迁移（子进程执行 + 日志实时显示）。

    设计（5 轮复盘）：m7 任务 = 长跑自动化（体力/挑战/宇宙）——
    子进程隔离（cwd/单例/配置零冲突，m7 官方 GUI 同款模式）；
    MARCH7TH_DOCKER_STARTED=true 跳过 first_run（auto_update=false 会直接
    退出）与结束 pause（input 会挂住子进程）；停止 = TerminateProcess。
    """

    def __init__(self, parent=None):
        super().__init__("任务中心", parent)
        self.set_status("March7th 任务模块（子进程执行）")
        self._proc = None
        self._current = None

        # 状态行
        self._led = QLabel("● 空闲")
        self._led.setStyleSheet("color: #7A90B0; font-size: 13px;")
        self._header.layout().addWidget(self._led)

        # 任务分组
        from gui.tasks.catalog import TASK_GROUPS
        self._buttons = {}
        for group, items in TASK_GROUPS:
            card = CardWidget()
            card_title(card, group)
            row = QHBoxLayout()
            row.setSpacing(8)
            for tid, name, desc in items:
                sub = QVBoxLayout()
                sub.setSpacing(2)
                btn = QPushButton(name)
                btn.setToolTip(desc)
                btn.setFixedWidth(110)
                btn.clicked.connect(lambda _, t=tid: self._start_task(t))
                self._buttons[tid] = btn
                sub.addWidget(btn)
                # 任务配置入口（m7 各任务自定义配置——读写 m7 config.yaml）
                from gui.tasks.config import schema_for_task
                if schema_for_task(tid) is not None:
                    cfg_btn = QPushButton("配置")
                    cfg_btn.setFixedWidth(110)
                    cfg_btn.setFixedHeight(24)
                    cfg_btn.setStyleSheet(
                        "font-size: 11px; color: #7A90B0;"
                        "border: 1px solid #24405F; border-radius: 4px;"
                        "background: transparent;")
                    cfg_btn.clicked.connect(
                        lambda _, t=tid: self._open_config(t))
                    sub.addWidget(cfg_btn)
                row.addLayout(sub)
            row.addStretch(1)
            card_layout(card).addLayout(row)
            self.content_layout.addWidget(card)

        # 日志区
        log_card = CardWidget()
        card_title(log_card, "任务日志")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setStyleSheet(
            "background: #0D1520; color: #B0C4DE; font-size: 12px;"
            "border: 1px solid #24405F; border-radius: 6px;")
        card_layout(log_card).addWidget(self._log)
        self.content_layout.addWidget(log_card, 1)

        # 底部控制
        self._stop_btn = QPushButton("停止任务")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_task)
        self._clear_btn = QPushButton("清空日志")
        self._clear_btn.clicked.connect(self._log.clear)
        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self._stop_btn)
        fl.addWidget(self._clear_btn)
        fl.addStretch(1)
        self.add_footer(footer)

    # ---------- 任务控制 ----------

    def _open_config(self, task_id):
        """任务配置对话框（m7 config.yaml 读写）。"""
        from gui.tasks.catalog import task_name
        from gui.tasks.config_dialog import TaskConfigDialog
        dlg = TaskConfigDialog(task_id, task_name(task_id), self)
        dlg.exec()

    def _start_task(self, task_id):
        from gui.tasks.catalog import task_name
        if self._proc is not None and self._proc.running:
            self._append(f"[提示] 已有任务运行中（{self._current}）——请先停止")
            return
        from gui.tasks.runner import TaskProcess
        self._current = task_id
        self._log.clear()
        self._append(f"[开始] 任务：{task_name(task_id)}（{task_id}）")
        self._set_running(True)
        proc = TaskProcess(task_id, self)
        proc.log_line.connect(self._append)
        proc.task_finished.connect(self._on_finished)
        proc.start()
        self._proc = proc

    def _stop_task(self):
        if self._proc is not None:
            self._append("[停止] 正在终止任务进程…")
            self._proc.stop()

    def _on_finished(self, exit_code):
        from gui.tasks.catalog import task_name
        name = task_name(self._current) if self._current else "任务"
        self._append(f"[完成] {name} 退出码 {exit_code}"
                     + ("（成功）" if exit_code == 0 else "（失败/被停止）"))
        self._current = None
        self._proc = None
        self._set_running(False)

    def _set_running(self, running):
        self._led.setText("● 运行中" if running else "● 空闲")
        self._led.setStyleSheet(
            "color: #4FD1C5; font-size: 13px;" if running
            else "color: #7A90B0; font-size: 13px;")
        self._stop_btn.setEnabled(running)
        for btn in self._buttons.values():
            btn.setEnabled(not running)

    def _append(self, line):
        self._log.appendPlainText(line)

    def shutdown(self):
        """GUI 关闭时终止残留任务进程（防后台孤儿进程继续点游戏）。"""
        if self._proc is not None:
            try:
                self._proc.stop()
                self._proc.waitFinished(3000)
            except Exception:
                pass
            self._proc = None


def error_page(source, error):
    """Bug 53：页面构造失败兜底页（显示错误而非空白/崩溃）。"""
    return placeholder_page(f"{source} 初始化失败", f"错误: {error}")


def placeholder_page(title, note):
    """占位页：卡片置顶（无顶部 stretch 空洞）。
    Bug 185：明确标注「功能开发中」——防止用户误以为 TODO 已实现。"""
    page = BasePage(title)
    card = CardWidget()
    card_layout(card)
    badge = BodyLabel("功能开发中")
    badge.setStyleSheet("color: #FFB454; font-weight: 700; font-size: 13px;")
    card_layout(card).addWidget(badge)
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
        self.frame_label = QLabel("实时画面加载中…")
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.frame_label.setMinimumHeight(200)
        self.frame_label.setStyleSheet(
            "background: #101826; border: 1px dashed #24405F; border-radius: 8px;"
            "color: #7A90B0;")
        card_layout(frame_card).addWidget(self.frame_label)
        cap_row = QHBoxLayout()
        self.capture_btn = QPushButton("立即刷新")
        self.capture_btn.clicked.connect(self._capture)
        cap_row.addWidget(self.capture_btn)
        cap_row.addStretch(1)
        card_layout(frame_card).addLayout(cap_row)
        self.content_layout.addWidget(frame_card, 1)

        # 实时自动刷新：抓帧周期 3s（页面可见时）
        from PySide6.QtCore import QTimer
        self._auto_refresh = QTimer(self)
        self._auto_refresh.setInterval(3000)
        self._auto_refresh.timeout.connect(self._capture_if_visible)
        self._auto_refresh.start()
        QTimer.singleShot(800, self._capture_if_visible)

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

    def _capture_if_visible(self):
        """实时自动刷新——仅页面可见时抓帧（同步抓帧仅 0.12s，3s 周期可接受）。"""
        if not self.isVisible():
            return
        self._capture()

    _FRAME_STYLE = (
        "background: #101826; border: 1px dashed #24405F; border-radius: 8px;"
        "color: #7A90B0;")

    def _show_pix(self, pix):
        """显示画面：pixmap 存临时文件 + 样式 background-image 显示——
        审查根因：本环境 QLabel.setPixmap 多次实测失效（pixmap() 返回 null）。
        """
        self.frame_label.clear()  # 清占位文本/旧 pixmap（防文字叠在图上）
        try:
            from pathlib import Path
            tmp = Path(__file__).resolve().parent.parent.parent / "logs" / "live_frame.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(tmp))
            self.frame_label.setStyleSheet(
                f"background-image: url({tmp.as_posix()}); background-repeat: no-repeat;"
                f"background-position: center; background-color: #101826;")
        except Exception:
            self.frame_label.setPixmap(pix)  # 兜底

    def _show_text(self, text):
        """显示文本：恢复样式表（先清 pixmap）。"""
        self.frame_label.clear()
        self.frame_label.setStyleSheet(self._FRAME_STYLE)
        self.frame_label.setText(text)

    def _capture(self):
        """抓帧并显示——主线程同步（截图仅 0.12s，3 秒一帧可接受）。

        审查根因（多轮实测）：① QThread 跨线程信号/QPixmap 链路不可靠；
        ② QLabel.setPixmap 后 pixmap() 返回 null 显示不出——改样式
        background-image 显示（pixmap 存临时文件）。
        """
        self.capture_btn.setEnabled(False)
        self.capture_btn.setText("抓取中…")
        try:
            import numpy as np
            from PIL import Image as PILImage
            from PIL.ImageQt import ImageQt
            from PySide6.QtGui import QPixmap
            from runtime.drivers.march7th.vision import March7thVision
            vision = March7thVision()
            shot = vision.take_screenshot()
            if shot is None:
                self._show_text("未获取到画面（游戏未启动或截图失败）")
                return
            img = shot[0]
            # 审查根因：March7th 截图 PIL 共享 numpy/mss buffer——
            # numpy 深拷贝成独立数组再转 PIL/QPixmap（实测该路径有效）
            arr = np.asarray(img).copy()
            pil = PILImage.fromarray(arr, "RGB") \
                if arr.ndim == 3 and arr.shape[2] == 3 else PILImage.fromarray(arr)
            pix = QPixmap.fromImage(ImageQt(pil))
            w = self.frame_label.width() or 800
            h = self.frame_label.height() or 400
            self._show_pix(pix.scaled(
                w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            self._show_text(f"截图失败: {type(e).__name__}: {e}")
        finally:
            self.capture_btn.setEnabled(True)
            self.capture_btn.setText("抓取画面")

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

        # Bug 303：统计扫描延迟到事件循环（页面初始化不阻塞 UI）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refresh)

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



class SettingsPage(BasePage):
    """设置页：可交互配置（VLM 模型保存到 QSettings）。"""

    def __init__(self, parent=None):
        super().__init__("设置", parent)
        self.set_status("模型与环境信息")

        card = CardWidget()
        cl = card_layout(card)

        # 模型配置（可改——不再只读）
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("VLM 分析模型:"))
        # qfluentwidgets.ComboBox 无 setEditable——用原生 QComboBox（可编辑）
        from PySide6.QtWidgets import QComboBox
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "qwen3-vl-plus", "qwen3-vl-flash", "qwen-vl-max",
            "qwen-vl-plus", "qwen-omni-turbo",
        ])
        from config import settings as _s
        self.model_combo.setCurrentText(
            _s.qwen_vlm_analyze_model() or "qwen3-vl-plus")
        row2.addWidget(self.model_combo)
        row2.addStretch(1)
        cl.addLayout(row2)
        hint = QLabel("保存后当前进程立即生效（VLM 识别/攻略分析用）")
        hint.setStyleSheet("color: #7A90B0; font-size: 12px;")
        cl.addWidget(hint)

        # 环境信息（只读）
        self._env_label = QLabel(self._env_info())
        self._env_label.setWordWrap(True)
        self._env_label.setStyleSheet("color: #7A90B0; font-size: 13px;")
        cl.addWidget(self._env_label)

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
        saved_model = s.value("vlm_model", "")
        if saved_model:
            self.model_combo.setCurrentText(str(saved_model))

    def _save(self):
        from PySide6.QtCore import QSettings
        from config import settings as _s
        s = QSettings("WorldExecutor", "Studio")
        # 模型保存：运行时覆盖（当前进程立即生效，不写 .env）
        model = self.model_combo.currentText().strip()
        if model:
            _s.set_override("QWEN_VLM_ANALYZE_MODEL", model)
            s.setValue("vlm_model", model)  # 下次启动 GUI 默认带入
        self._env_label.setText(self._env_info())
        QMessageBox.information(
            self, "设置",
            f"已保存：VLM 模型={model}" if model else "已保存")
