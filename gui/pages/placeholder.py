from PySide6.QtWidgets import QVBoxLayout, QWidget

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
        self._p = placeholder_page(
            "世界图 World Graph",
            "GUI-M0.2: Room Graph 节点图 + Abstraction Level（Room/Portal/Objective）")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)


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
        self._p = placeholder_page(
            "知识库 Knowledge Library",
            "GUI-M0.2: 知识包树 + validator 面板 + 模板网格 + Package Version")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)


class StudioPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = placeholder_page(
            "工作室 Studio",
            "GUI-M0.4: 视频分析 / 模板提取 / 模型探测")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = placeholder_page(
            "设置 Settings",
            "GUI-M0.4: 引擎路径 / VLM 模型 / 界面")
        layout = QVBoxLayout(self)
        layout.addWidget(self._p)
