from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

from gui.state_machine_view import StateMachineView
from qfluentwidgets import (CardWidget, ComboBox, PrimaryPushButton,
                            PushButton, StrongBodyLabel, SubtitleLabel)


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

STATUS_TEXT = {
    "pending": "待命",
    "running": "执行中",
    "done": "完成",
    "failed": "失败",
    "skipped": "跳过",
}
STATUS_COLOR = {
    "pending": "#7A90B0",
    "running": "#4FD1C5",
    "done": "#3BA55D",
    "failed": "#FF6B6B",
    "skipped": "#5A6B82",
}

CATEGORY_TEXT = {
    "F1": "F1 输入失败",
    "F2": "F2 视觉失败",
    "F3": "F3 决策漂移",
    "EMERGENCY": "EMERGENCY 人工介入",
}


def category_text(code):
    return CATEGORY_TEXT.get(code, f"{code}" if code else "unknown")


class TargetRow(QFrame):
    def __init__(self, target_id, room, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setObjectName("targetRow")
        self.setStyleSheet(
            "#targetRow { background: #16283F; border: 1px solid #24405F; border-radius: 8px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self.name_label = StrongBodyLabel(target_id)
        self.room_label = QLabel(room)
        self.room_label.setStyleSheet("color: #7A90B0;")
        self.status_label = QLabel("待命")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.name_label)
        lay.addWidget(self.room_label)
        lay.addStretch(1)
        lay.addWidget(self.status_label)
        self.set_status("pending")

    def set_status(self, status):
        self._status = status
        color = STATUS_COLOR.get(status, "#7A90B0")
        self.status_label.setText(STATUS_TEXT.get(status, status))
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 700;")


class ObservationSnapshot(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        card_title(self, "当前观测快照")
        self._body = QLabel("—")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #7A90B0;")
        card_layout(self).addWidget(self._body)
        card_layout(self).addStretch(1)

    def update_snapshot(self, observer, target, confidence, room):
        parts = [f"observer={observer}", f"target={target}"]
        if confidence is not None:
            parts.append(f"confidence={confidence:.2f}")
        if room:
            parts.append(f"room={room}")
        self._body.setText("  ·  ".join(parts))


HEALTH_LABELS = {
    "window": "窗口",
    "capture": "截屏",
    "ocr": "OCR",
    "vlm": "VLM",
    "input": "输入权限",
}


class RuntimeHealthBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._items = {}
        for key, label in HEALTH_LABELS.items():
            box = QLabel(f"[?] {label}")
            box.setStyleSheet("color: #7A90B0; font-size: 11px; border: 1px solid #24405F;"
                              "border-radius: 4px; padding: 2px 8px;")
            lay.addWidget(box)
            self._items[key] = box
        lay.addStretch(1)

    def set_health(self, health):
        for key, ok in health.items():
            box = self._items.get(key)
            if box is None:
                continue
            if key == "input" and ("input_l0" in health or "input_l1" in health):
                l0 = "L0✓" if health.get("input_l0") else "L0✗"
                l1 = "L1✓" if health.get("input_l1") else "L1✗"
                l2 = "L2?" if health.get("input_l2") is None else ("L2✓" if health.get("input_l2") else "L2✗")
                mark = "✓" if ok else "✗"
                color = "#3BA55D" if ok else "#FF6B6B"
                box.setText(f"[{mark}] 输入 {l0} {l1} {l2}")
                box.setStyleSheet(f"color: {color}; font-size: 11px; border: 1px solid #24405F;"
                                  "border-radius: 4px; padding: 2px 8px;")
                continue
            mark = "✓" if ok else "✗"
            color = "#3BA55D" if ok else "#FF6B6B"
            label = HEALTH_LABELS.get(key, key)
            box.setText(f"[{mark}] {label}")
            box.setStyleSheet(f"color: {color}; font-size: 11px; border: 1px solid #24405F;"
                              "border-radius: 4px; padding: 2px 8px;")


class FailureInspector(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        card_title(self, "失败检查器 Failure Inspector")
        self._body = QLabel("尚无失败记录 —")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #7A90B0;")
        card_layout(self).addWidget(self._body)
        card_layout(self).addStretch(1)

    def on_failure(self, run_no, state, observation, action, input_info, reason, category=None):
        cat_text = f"[{category}] " if category else ""
        lines = [
            f"Run #{run_no}  FAILED  {cat_text}",
            f"State: {state or '—'}",
            f"Last observation: {observation or '—'}",
            f"Action: {action or '—'}",
            f"Input: {input_info or '—'}",
            f"Reason: {reason or '—'}",
        ]
        self._body.setText("\n".join(lines))
        self._body.setStyleSheet("color: #FF6B6B;")

    def reset(self):
        self._body.setText("尚无失败记录 —")
        self._body.setStyleSheet("color: #7A90B0;")


class CommandDeck(QWidget):
    run_requested = Signal(list)
    stop_requested = Signal()

    def __init__(self, targets, parent=None):
        super().__init__(parent)
        self._run_no = 0
        self._last_state = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = SubtitleLabel("指挥台 Command Deck")
        title.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 1px;")
        self.led = QLabel("● 空闲")
        self.led.setStyleSheet("color: #7A90B0; font-size: 12px;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.led)
        layout.addLayout(header)

        control_bar = QHBoxLayout()
        self.target_combo = ComboBox()
        self.target_combo.addItems(["全部目标"] + [t["id"] for t in targets])
        self.start_btn = PrimaryPushButton("开始收集")
        self.start_btn.setFixedWidth(130)
        self.stop_btn = PushButton("停止")
        self.stop_btn.setEnabled(False)
        control_bar.addWidget(QLabel("目标:"))
        control_bar.addWidget(self.target_combo)
        control_bar.addStretch(1)
        control_bar.addWidget(self.stop_btn)
        control_bar.addWidget(self.start_btn)
        layout.addLayout(control_bar)

        self.sm_view = StateMachineView()
        self.sm_view.setFixedHeight(190)
        layout.addWidget(self.sm_view)

        bottom = QHBoxLayout()
        queue_card = CardWidget()
        card_title(queue_card, "目标队列")
        self.queue_layout = QVBoxLayout()
        self.queue_layout.setSpacing(8)
        self.rows = {}
        for t in targets:
            row = TargetRow(t["id"], t.get("room", ""))
            self.rows[t["id"]] = row
            self.queue_layout.addWidget(row)
        self.queue_layout.addStretch(1)
        card_layout(queue_card).addLayout(self.queue_layout)
        bottom.addWidget(queue_card, 3)

        self.snapshot = ObservationSnapshot()
        bottom.addWidget(self.snapshot, 2)
        layout.addLayout(bottom, 1)

        self.health_bar = RuntimeHealthBar()
        layout.addWidget(self.health_bar)

        self.inspector = FailureInspector()
        layout.addWidget(self.inspector)

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self.stop_requested)

    def set_health(self, health):
        self.health_bar.set_health(health)

    def _on_start(self):
        sel = self.target_combo.currentText()
        targets = [] if sel == "全部目标" else [sel]
        self.run_requested.emit(targets)

    def on_event(self, event):
        if event.type == "run_started":
            self._run_no += 1
            self.led.setText("● 运行中")
            self.led.setStyleSheet("color: #4FD1C5; font-size: 12px;")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif event.type == "run_finished":
            self.led.setText("● 空闲")
            self.led.setStyleSheet("color: #7A90B0; font-size: 12px;")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        elif event.type == "state_changed":
            self._last_state = event.to_state
            self.sm_view.on_state(event.from_state, event.to_state, event.detail)
        elif event.type == "target_progress":
            ctx = event.context
            status = ctx.get("status")
            if ctx.get("target") in self.rows and status:
                self.rows[ctx["target"]].set_status(status)
            if status == "failed":
                self.inspector.on_failure(
                    run_no=self._run_no, state=self._last_state,
                    observation=self.snapshot._body.text(),
                    action="—", input_info="—",
                    reason=ctx.get("reason") or "目标失败",
                    category=category_text(ctx.get("category")))
        elif event.type == "observation":
            ctx = event.context
            self.snapshot.update_snapshot(
                ctx.get("observer"), event.detail or ctx.get("target"),
                ctx.get("confidence"), ctx.get("room"))
        elif event.type == "action_executed":
            ctx = event.context
            if ctx.get("success") is False:
                reason = ctx.get("error") or "unknown"
                suggested = ("重启并以管理员身份运行" if "uipi" in reason.lower()
                             else "检查游戏窗口是否在前台")
                self.inspector.on_failure(
                    run_no=self._run_no, state=self._last_state,
                    observation=self.snapshot._body.text(),
                    action=event.detail, input_info=f"{ctx.get('backend')} ✗",
                    reason=f"{reason} → 建议: {suggested}",
                    category="F1 输入失败")
        elif event.type == "pause_requested":
            self.led.setText("⏸ 已暂停")
            self.led.setStyleSheet("color: #FFB020; font-size: 12px;")
        elif event.type == "human_intervention":
            ctx = event.context
            self.led.setText("⚠ 人工介入")
            self.led.setStyleSheet("color: #FFB020; font-size: 12px;")
            self.inspector.on_failure(
                run_no=self._run_no, state=self._last_state,
                observation=self.snapshot._body.text(),
                action="—", input_info="—",
                reason=f"人工介入: {ctx.get('reason')} {ctx.get('detail', '')}",
                category="EMERGENCY")

    def reset(self):
        self.sm_view.reset()
        for row in self.rows.values():
            row.set_status("pending")
        self.snapshot.update_snapshot("—", "—", None, "")
        self.inspector.reset()
