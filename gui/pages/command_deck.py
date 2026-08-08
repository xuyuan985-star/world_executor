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


class CommandDeck(QWidget):
    run_requested = Signal(list)
    stop_requested = Signal()

    def __init__(self, targets, parent=None):
        super().__init__(parent)
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

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self.stop_requested)

    def _on_start(self):
        sel = self.target_combo.currentText()
        targets = [] if sel == "全部目标" else [sel]
        self.run_requested.emit(targets)

    def on_event(self, event):
        if event.type == "run_started":
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
            self.sm_view.on_state(event.from_state, event.to_state, event.detail)
        elif event.type == "target_progress":
            target = event.context.get("target")
            status = event.context.get("status")
            if target in self.rows and status:
                self.rows[target].set_status(status)
        elif event.type == "observation":
            ctx = event.context
            self.snapshot.update_snapshot(
                ctx.get("observer"), event.detail or ctx.get("target"),
                ctx.get("confidence"), ctx.get("room"))

    def reset(self):
        self.sm_view.reset()
        for row in self.rows.values():
            row.set_status("pending")
        self.snapshot.update_snapshot("—", "—", None, "")
