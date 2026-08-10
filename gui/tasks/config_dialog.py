"""任务配置对话框：按任务 schema 生成表单 → 读写 m7 config.yaml。"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout)


class TaskConfigDialog(QDialog):
    def __init__(self, task_id, task_name, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.setWindowTitle(f"任务配置 - {task_name}")
        self.setMinimumWidth(420)

        from gui.tasks.config import load_config, save_config, schema_for_task

        self._data = load_config()
        if self._data is None:
            self._data = {}
        info = schema_for_task(task_id)
        self._fields = {}
        self._keys = []

        lay = QVBoxLayout(self)
        if info is None:
            lay.addWidget(QLabel("该任务暂无可用配置项（复杂配置请编辑 m7 config.yaml）"))
            self._finish_buttons(lay)
            return

        group, items = info
        form = QFormLayout()
        for key, spec in items:
            kind = spec[0]
            label = spec[1]
            if kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(self._data.get(key, False)))
            elif kind == "int":
                lo = spec[2] if len(spec) > 2 else 0
                hi = spec[3] if len(spec) > 3 else 100
                w = QSpinBox()
                w.setRange(lo, hi)
                try:
                    w.setValue(int(self._data.get(key, 0)))
                except (TypeError, ValueError):
                    w.setValue(lo)
            elif kind == "choice":
                w = QComboBox()
                w.addItems(spec[2])
                cur = str(self._data.get(key, ""))
                if cur in spec[2]:
                    w.setCurrentText(cur)
            else:  # text
                w = QLineEdit(str(self._data.get(key, "")))
            self._fields[key] = w
            self._keys.append(key)
            form.addRow(label, w)
        lay.addLayout(form)

        hint = QLabel("保存写入 m7 config.yaml（写前自动备份 .bak）；"
                      "列表型配置（体力计划/队伍/兑换码）请直接编辑 config.yaml")
        hint.setStyleSheet("color: #7A90B0; font-size: 12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._finish_buttons(lay)

    def _finish_buttons(self, lay):
        row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(save_btn)
        row.addWidget(cancel_btn)
        lay.addLayout(row)

    def _save(self):
        from gui.tasks.config import save_config
        updates = {}
        for key in self._keys:
            w = self._fields[key]
            if isinstance(w, QCheckBox):
                updates[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                updates[key] = w.value()
            elif isinstance(w, QComboBox):
                updates[key] = w.currentText()
            else:
                updates[key] = w.text().strip()
        ok, err = save_config(updates)
        if ok:
            self.accept()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", str(err))
