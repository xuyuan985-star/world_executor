"""CommandDeck（重构版）：BasePage 框架 + 指挥台业务。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from gui.pages.base_page import BasePage, card_layout, card_title
from qfluentwidgets import CardWidget, ComboBox, PrimaryPushButton, PushButton, StrongBodyLabel


# ---- 状态常量 ----

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
    "F1_TEMPLATE": "F1 模板未命中",
    "F1_PERMISSION": "F1 权限失败",
    "F1_EXEC": "F1 执行器异常",
    "F1_INTERNAL": "F1 内部错误",
    "F2": "F2 视觉失败",
    "F2_COORD": "F2 坐标异常",
    "F2_TIMEOUT": "F2 验证超时",
    "F3": "F3 决策漂移",
    "F4_VISION": "F4 视觉不可信",
    "F4_DARK": "F4 黑屏",
    "F4_WRONG_WINDOW": "F4 窗口错误",
    "F4_CONFLICT": "F4 OCR/VLM 冲突",
    "F4_LOW_CONF": "F4 置信度低",
    "F4_EXPIRED": "F4 证据过期",
    "F4_NOT_VERIFIED": "F4 未验证",
    "F4_FRAME": "F4 帧异常",
    "F5_ACTION_BLOCK": "F5 动作被策略拦截",
    "F5_RISK_HIGH": "F5 风险过高",
    "EMERGENCY": "EMERGENCY 人工介入",
}


def category_text(code):
    return CATEGORY_TEXT.get(code, f"{code}" if code else "unknown")


STATUS_TEXT_CN = {"pending": "待命", "running": "进行中", "succeeded": "完成",
                  "failed": "失败", "interrupted": "中断"}


def _status_color(status):
    from PySide6.QtGui import QColor
    return QColor({"running": "#4FD1C5", "succeeded": "#3BA55D",
                   "failed": "#E64545", "interrupted": "#FFB020"}.get(status, "#7A90B0"))


# ---- 目标行 ----

class TargetRow(QFrame):
    def __init__(self, target_id, room, name=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setObjectName("targetRow")
        self.setStyleSheet(
            "#targetRow { background: #16283F; border: 1px solid #24405F; border-radius: 8px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self.name_label = StrongBodyLabel(name or target_id)
        self.room_label = QLabel(room)
        self.room_label.setStyleSheet("color: #7A90B0;")
        self.status_label = QLabel("待命")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.name_label)
        lay.addWidget(self.room_label)
        lay.addStretch(1)
        lay.addWidget(self.status_label)
        self.set_status("pending")

    VALID_TRANSITIONS = {
        "pending": {"running"},
        "running": {"succeeded", "failed", "interrupted"},
        "interrupted": {"running", "succeeded"},
    }

    ALL_STATUS = {"pending", "running", "succeeded", "failed", "interrupted"}

    def set_status(self, status):
        if status not in self.ALL_STATUS:
            return
        cur = getattr(self, "_status", "pending")
        allowed = self.VALID_TRANSITIONS.get(cur, set())
        if cur != "pending" and status not in allowed:
            return
        self._status = status
        color = STATUS_COLOR.get(status, "#7A90B0")
        self.status_label.setText(STATUS_TEXT.get(status, status))
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 700;")


# ---- 实时观测卡片 ----

class ObservationSnapshot(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        card_title(self, "实时观测")
        self._shot = QLabel("游戏画面（待真机接入）")
        self._shot.setAlignment(Qt.AlignCenter)
        self._shot.setMinimumHeight(180)
        self._shot.setStyleSheet(
            "background: #101826; border: 1px dashed #24405F; border-radius: 8px;"
            "color: #7A90B0;")
        card_layout(self).addWidget(self._shot)
        self._body = QLabel("—")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #7A90B0;")
        card_layout(self).addWidget(self._body)
        card_layout(self).addStretch(1)
        self._history = []

    def set_frame(self, pixmap_or_none):
        if pixmap_or_none is not None:
            self._shot.setPixmap(pixmap_or_none)
        else:
            self._shot.setText("游戏画面（待真机接入）")

    def update_snapshot(self, observer, target, confidence, room):
        lines = [f"目标: {target}",
                 f"识别: {observer}",
                 f"置信: {confidence:.0%}" if confidence is not None else "置信: --"]
        if room:
            lines.append(f"区域: {room}")
        snapshot = "\n".join(lines)
        self._body.setText(snapshot)
        self._body.setStyleSheet("color: #E8F0FE; font-size: 13px;")
        self._push(snapshot)

    def text(self):
        return self._body.text()

    def history_text(self, last=5):
        return "\n".join(self._history[-last:])

    def _push(self, text):
        self._history.append(text)
        self._history = self._history[-20:]


# ---- 健康栏 ----

HEALTH_LABELS = {
    "window": "窗口",
    "foreground": "前台",
    "admin": "提权",
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


# ---- 失败检查器 ----

class FailureInspector(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        card_title(self, "失败检查器")
        self._body = QLabel("尚无失败记录 —")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #7A90B0;")
        card_layout(self).addWidget(self._body)
        card_layout(self).addStretch(1)
        self.history = []

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
        self.history.append((run_no, state, reason, category))
        self.history = self.history[-20:]
        recent = [
            f"#{r} [{cat or '-'}] {st or '-'} → {rr or '-'}"
            for r, st, rr, cat in self.history[-5:]
        ]
        self._body.setText("\n".join(lines + [""] + recent))
        self._body.setStyleSheet("color: #FF6B6B;")

    def reset(self):
        self._body.setText("尚无失败记录 —")
        self._body.setStyleSheet("color: #7A90B0;")


# ---- 指挥台主页面 ----

class CommandDeck(BasePage):
    run_requested = Signal(list)
    stop_requested = Signal()

    def __init__(self, targets, parent=None):
        super().__init__("指挥台", parent)
        self._run_no = 0
        self._last_state = None
        self._targets = targets or []

        # Header：状态 LED
        self.led = QLabel("● 空闲")
        self.led.setStyleSheet("color: #7A90B0; font-size: 12px;")
        self._header.layout().addWidget(self.led)
        self.set_status("选择目标后开始")

        # ---- Content 上半：控制栏 ----
        control_card = CardWidget()
        control_card.setStyleSheet("background: #16283F;")
        control_layout = QHBoxLayout(control_card)
        control_layout.setContentsMargins(16, 12, 16, 12)
        control_layout.setSpacing(12)

        self.target_combo = ComboBox()
        self._map_groups = {}
        self._region_groups = {}
        combo_items = ["全部目标"]
        for t in self._targets:
            map_name = t.get("map_name") or "未分组"
            region = t.get("room") or t.get("region") or "未知区域"
            if map_name not in self._map_groups:
                self._map_groups[map_name] = []
                combo_items.append(f"〔地图〕{map_name}")
            self._map_groups[map_name].append(t)
            key = (map_name, region)
            if key not in self._region_groups:
                self._region_groups[key] = []
                combo_items.append(f"    〔区域〕{region}")
            self._region_groups[key].append(t)
        self.target_combo.addItems(combo_items)

        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["模拟执行", "真机执行"])
        try:
            from PySide6.QtCore import QSettings
            if QSettings("WorldExecutor", "Studio").value("default_mode") == "real":
                self.mode_combo.setCurrentIndex(1)
        except Exception:
            pass

        self.start_btn = PrimaryPushButton("开始任务")
        self.start_btn.setFixedWidth(120)
        self.stop_btn = PushButton("停止")
        self.stop_btn.setEnabled(False)

        control_layout.addWidget(QLabel("目标:"))
        control_layout.addWidget(self.target_combo)
        control_layout.addStretch(1)
        control_layout.addWidget(self.mode_combo)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.start_btn)
        self.content_layout.addWidget(control_card)

        # 运行状态行
        self.run_status = QLabel("● 空闲 — 选择目标后开始")
        self.run_status.setStyleSheet("font-size: 15px; font-weight: 700; color: #7A90B0;")
        self.content_layout.addWidget(self.run_status)

        # ---- Content 主体：队列 / 观测 ----
        bottom = QHBoxLayout()
        queue_card = CardWidget()
        card_title(queue_card, "任务队列")
        self.target_tree = QTreeWidget()
        self.target_tree.setHeaderLabels(["目标", "状态"])
        self.target_tree.setAlternatingRowColors(True)
        self.rows = {}
        self._map_nodes = {}
        self._region_nodes = {}
        for t in self._targets:
            map_name = t.get("map_name") or "未分组"
            region = t.get("room") or t.get("region") or "未知区域"
            if map_name not in self._map_nodes:
                node = QTreeWidgetItem([map_name, ""])
                self.target_tree.addTopLevelItem(node)
                self._map_nodes[map_name] = node
            rkey = (map_name, region)
            if rkey not in self._region_nodes:
                rnode = QTreeWidgetItem([f"  {region}", ""])
                self._map_nodes[map_name].addChild(rnode)
                self._region_nodes[rkey] = rnode
            name = t.get("name") or t["id"]
            leaf = QTreeWidgetItem([f"    {name}", "待命"])
            self._region_nodes[rkey].addChild(leaf)
            self.rows[t["id"]] = leaf
            leaf.setData(0, Qt.UserRole, t["id"])
        self.target_tree.expandToDepth(1)
        card_layout(queue_card).addWidget(self.target_tree)
        bottom.addWidget(queue_card, 2)

        self.snapshot = ObservationSnapshot()
        bottom.addWidget(self.snapshot, 3)
        self.content_layout.addLayout(bottom, 1)

        # 失败检查器
        self.inspector = FailureInspector()
        self.content_layout.addWidget(self.inspector)

        # ---- Footer：健康栏折叠 ----
        footer_widget = QWidget()
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        hrow = QHBoxLayout()
        self.health_toggle = PushButton("系统状态 ▼")
        self.health_toggle.setFixedWidth(110)
        self.health_toggle.clicked.connect(self._toggle_health)
        hrow.addWidget(self.health_toggle)
        hrow.addStretch(1)
        footer_layout.addLayout(hrow)
        self.health_bar = RuntimeHealthBar()
        footer_layout.addWidget(self.health_bar)
        self.add_footer(footer_widget)

        # 信号
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self.stop_requested)

    def set_starting(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.led.setText("● 初始化")
        self.led.setStyleSheet("color: #FFB020; font-size: 12px;")

    def set_stopping(self):
        self.stop_btn.setEnabled(False)
        self.led.setText("● 停止中")
        self.led.setStyleSheet("color: #FFB020; font-size: 12px;")

    def set_health_status(self, text, busy=False):
        self.led.setText("● " + text)
        self.led.setStyleSheet("color: #FFB020;" if busy else "color: #7A90B0;")
        self.start_btn.setEnabled(not busy)

    def set_health(self, health):
        self.health_bar.set_health(health)

    def _toggle_health(self):
        vis = not self.health_bar.isVisible()
        self.health_bar.setVisible(vis)
        self.health_toggle.setText("系统状态 ▲" if vis else "系统状态 ▼")

    def set_run_status(self, text, busy=False):
        self.run_status.setText(text)
        color = "#4FD1C5" if busy else ("#7A90B0" if "空闲" in text else "#FFB020")
        self.run_status.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {color};")

    def mode(self):
        return "real" if self.mode_combo.currentIndex() == 1 else "dry"

    def _resolve_selection(self, sel):
        if sel == "全部目标":
            return [t["id"] for t in self._targets]
        if sel.startswith("〔地图〕"):
            mname = sel.replace("〔地图〕", "")
            return [t["id"] for t in self._map_groups.get(mname, [])]
        if "〔区域〕" in sel:
            region = sel.split("〔区域〕")[1]
            out = []
            for (mname, rname), lst in self._region_groups.items():
                if rname == region:
                    out.extend(t["id"] for t in lst)
            return out
        return [sel] if sel in self.rows else []

    def _on_start(self):
        sel = self.target_combo.currentText()
        targets = self._resolve_selection(sel)
        if not targets:
            self.led.setText("● 目标不存在: " + sel)
            self.led.setStyleSheet("color: #E64545; font-size: 12px;")
            return
        self.run_requested.emit(targets)

    def on_event(self, event):
        if event.type == "run_started":
            self._run_no += 1
            self.led.setText("● 运行中")
            self.set_run_status("● 正在搜索宝箱", busy=True)
            self.led.setStyleSheet("color: #4FD1C5; font-size: 12px;")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif event.type == "run_finished":
            result = event.context.get("result", "")
            if result == "gate_blocked":
                # G3 门槛拦截——显示可行动原因（中文）
                reasons = event.context.get("reasons") or []
                fails = event.context.get("fails") or []
                msg = "执行被拦截（G3 能力门槛）"
                if reasons:
                    msg += "：\n" + "\n".join(str(r) for r in reasons[:4])
                elif fails:
                    msg += "：" + "、".join(str(f) for f in fails[:4])
                self.led.setText("● " + msg[:100])
                self.led.setStyleSheet("color: #FFB454; font-size: 12px;")
                self.set_run_status("● 执行被拦截（环境不满足）")
            elif result in ("invalid", "crashed"):
                err = event.context.get("error") or event.context.get("fails")
                self.led.setText("● 失败: " + result + (f" ({err})" if err else ""))
                self.led.setStyleSheet("color: #E64545; font-size: 12px;")
                self.set_run_status("● 执行失败")
            else:
                self.led.setText("● 空闲")
                self.led.setStyleSheet("color: #7A90B0; font-size: 12px;")
                self.set_run_status("● 完成")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        elif event.type == "state_changed":
            self._last_state = event.to_state
        elif event.type == "target_progress":
            ctx = event.context
            status = ctx.get("status")
            if ctx.get("target") in self.rows and status:
                leaf = self.rows[ctx["target"]]
                leaf.setText(1, STATUS_TEXT.get(status, status))
                leaf.setForeground(1, _status_color(status))
            if status == "failed":
                self.inspector.on_failure(
                    run_no=self._run_no, state=self._last_state,
                    observation=self.snapshot.text(),
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
                    observation=self.snapshot.text(),
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
                observation=self.snapshot.text(),
                action="—", input_info="—",
                reason=f"人工介入: {ctx.get('reason')} {ctx.get('detail', '')}",
                category="EMERGENCY")
        else:
            import logging
            logging.getLogger("gui.command_deck").warning(
                "未处理事件: %s", event.type)

    def reset(self):
        for leaf in self.rows.values():
            leaf.setText(1, "待命")
            leaf.setForeground(1, _status_color("pending"))
        self.led.setText("● 空闲")
        self.led.setStyleSheet("color: #7A90B0; font-size: 12px;")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.snapshot.update_snapshot("—", "—", None, "")
        self.inspector.reset()
