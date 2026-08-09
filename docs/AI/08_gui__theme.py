# gui/theme.py

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from qfluentwidgets import Theme, qconfig, setTheme, setThemeColor

BG_DEEP = "#0B1524"
BG_PANEL = "#0F1B2D"
BG_CARD = "#16283F"
BG_CARD_HOVER = "#1B3050"
BORDER = "#24405F"
ACCENT = "#4FD1C5"
ACCENT_DIM = "#2A7D78"
TEXT_MAIN = "#E6F1FF"
TEXT_MUTED = "#7A90B0"
WARN = "#FFB454"
DANGER = "#FF6B6B"
OK = "#4FD1C5"

STATE_COLORS = {
    "INIT": TEXT_MUTED,
    "CHECK_WORLD_STATE": "#7FB3FF",
    "NAVIGATING": OK,
    "PORTAL_TRANSITION": "#8E7CFF",
    "PORTAL_TRANSITION_FAILED": DANGER,
    "VERIFYING": WARN,
    "INTERACTING": "#FF8FA3",
    "EVENT_INTERRUPT": DANGER,
    "RECOVERING": WARN,
    "DONE": OK,
    "ABORT": DANGER,
}

GLOBAL_QSS = f"""
QWidget {{
    font-family: "Microsoft YaHei UI";
    color: {TEXT_MAIN};
}}
#titleBar {{
    background: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}
#navigationInterface {{
    background: {BG_DEEP};
    border-right: 1px solid {BORDER};
}}
#stackedWidget {{
    background: {BG_PANEL};
}}
#brandLabel {{
    color: {TEXT_MAIN};
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 2px;
}}
#brandSubLabel {{
    color: {TEXT_MUTED};
    font-size: 10px;
    letter-spacing: 1px;
}}
#statusLedLabel {{
    font-size: 11px;
}}
#stateLogView {{
    background: {BG_DEEP};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
"""


def apply_theme(app):
    qconfig.theme = Theme.DARK
    setThemeColor(QColor(ACCENT))
    app.setStyleSheet(GLOBAL_QSS)

```
