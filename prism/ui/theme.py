from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QLinearGradient


@dataclass(frozen=True)
class Palette:
    """Every colour the window uses, in one place.

    The window is always dark so the lighting previews glow the way the real
    LEDs do, and the accent runs violet to cyan, the colours a prism splits light into.
    """

    background: str = "#0c0e13"
    sidebar: str = "#10131a"
    card: str = "#161a23"
    raised: str = "#1d2230"
    border: str = "#252b3a"
    text: str = "#e8ecf3"
    dim: str = "#8b95a8"
    faint: str = "#566075"
    accent: str = "#8b5cf6"
    accent_end: str = "#22d3ee"
    good: str = "#34d399"
    warn: str = "#fbbf24"
    bad: str = "#f87171"

    def accent_gradient(self, x1: float, y1: float, x2: float, y2: float) -> QLinearGradient:
        """Build the violet to cyan gradient used for highlights and charts.

        @param x1: where the gradient starts, horizontally.
        @param y1: where it starts, vertically.
        @param x2: where it ends, horizontally.
        @param y2: where it ends, vertically.
        @return: the gradient.
        """
        gradient = QLinearGradient(x1, y1, x2, y2)
        gradient.setColorAt(0.0, QColor(self.accent))
        gradient.setColorAt(1.0, QColor(self.accent_end))
        return gradient


def stylesheet(palette: Palette) -> str:
    """Build the Qt stylesheet, which styles widgets by object name.

    @param palette: the colours.
    @return: the stylesheet.
    """
    p = palette
    return f"""
    * {{ font-family: "Inter", "Noto Sans", "Cantarell", sans-serif; }}
    QWidget {{ color: {p.text}; font-size: 10pt; }}
    QMainWindow, QDialog, #page {{ background: {p.background}; }}
    QToolTip {{ background: {p.raised}; color: {p.text}; border: 1px solid {p.border}; padding: 4px 8px; }}

    #sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
    #brand {{ font-size: 15pt; font-weight: 700; letter-spacing: 1px; }}
    #brandTag {{ color: {p.faint}; font-size: 8pt; letter-spacing: 2px; }}
    QPushButton#nav {{
        text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
        color: {p.dim}; font-weight: 600; background: transparent;
    }}
    QPushButton#nav:hover {{ background: {p.card}; color: {p.text}; }}
    QPushButton#nav:checked {{ background: {p.raised}; color: {p.text}; }}

    #title {{ font-size: 20pt; font-weight: 700; }}
    #subtitle, #dim {{ color: {p.dim}; }}
    #faint {{ color: {p.faint}; font-size: 9pt; }}
    #section {{ color: {p.faint}; font-size: 8pt; font-weight: 700; letter-spacing: 2px; }}
    #big {{ font-size: 24pt; font-weight: 700; }}
    #unit {{ color: {p.dim}; font-size: 11pt; }}
    #banner {{
        background: rgba(251, 191, 36, 0.10); border: 1px solid rgba(251, 191, 36, 0.35);
        border-radius: 10px; padding: 8px 12px; color: {p.warn};
    }}
    #pill {{
        background: {p.raised}; border: 1px solid {p.border}; border-radius: 9px;
        padding: 2px 10px; color: {p.dim}; font-size: 8pt; font-weight: 600;
    }}
    #pillAccent {{
        background: rgba(139, 92, 246, 0.18); border: 1px solid rgba(139, 92, 246, 0.5);
        border-radius: 9px; padding: 2px 10px; color: #c4b5fd; font-size: 8pt; font-weight: 600;
    }}

    #card {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 14px; }}
    #card:hover {{ border-color: #323a4d; }}
    #cardSelected {{ background: {p.raised}; border: 1px solid {p.accent}; border-radius: 14px; }}

    QPushButton {{
        background: {p.raised}; border: 1px solid {p.border}; border-radius: 9px;
        padding: 7px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.card}; }}
    QPushButton:disabled {{ color: {p.faint}; border-color: {p.border}; }}
    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent_end});
        border: none; color: white;
    }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9d74ff, stop:1 #4fe0f4);
    }}
    QPushButton#danger:hover {{ border-color: {p.bad}; color: {p.bad}; }}
    QPushButton#segment {{ border-radius: 0; border-right: none; padding: 6px 14px; }}
    QPushButton#segmentFirst {{
        border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: none; padding: 6px 14px;
    }}
    QPushButton#segmentLast {{ border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 6px 14px; }}
    QPushButton#segment:checked, QPushButton#segmentFirst:checked, QPushButton#segmentLast:checked,
    QPushButton#chip:checked {{
        background: rgba(139, 92, 246, 0.22); border-color: {p.accent}; color: white;
    }}
    QPushButton#chip {{ padding: 8px 12px; border-radius: 10px; }}

    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
        background: {p.raised}; border: 1px solid {p.border}; border-radius: 9px; padding: 6px 10px;
        selection-background-color: {p.accent};
    }}
    QComboBox:hover, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised}; border: 1px solid {p.border}; selection-background-color: {p.accent};
        outline: none; padding: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0; border: none;
    }}

    QSlider::groove:horizontal {{ height: 6px; background: {p.raised}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent_end});
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: white; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: none;
    }}

    QMenu {{ background: {p.raised}; border: 1px solid {p.border}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {p.accent}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p.border}; background: {p.raised};
    }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}

    #toast {{
        background: {p.raised}; border: 1px solid {p.accent}; border-radius: 12px; padding: 10px 16px;
    }}
    """
