"""
PDF Studio - 全局界面补充样式（提升控件与背景区分度）
"""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication
from qfluentwidgets import isDarkTheme

STYLE_MARKER = "/* PDF_STUDIO_SUPPLEMENT */"


def _resolve_dark(dark: bool | None) -> bool:
    return isDarkTheme() if dark is None else dark


def palette(dark: bool | None = None) -> dict[str, str]:
    if _resolve_dark(dark):
        return {
            "page_bg": "#1c1c1e",
            "card_bg": "#252526",
            "card_border": "#454545",
            "input_bg": "#2d2d30",
            "input_bg_hover": "#333337",
            "input_bg_focus": "#2d2d30",
            "input_border": "#555555",
            "input_border_hover": "#6b7280",
            "accent": "#60CDFF",
            "btn_secondary_bg": "#2d2d30",
            "btn_secondary_hover": "#3a3a3f",
            "btn_secondary_border": "#555555",
            "tab_inactive": "#2a2a2c",
            "segmented_track": "#2d2d30",
            "muted_text": "#9ca3af",
            "drop_bg": "#252526",
            "drop_border": "#5a5a5a",
            "drop_hover_bg": "rgba(96, 205, 255, 0.12)",
            "tool_btn_bg": "#2d2d30",
            "tool_btn_hover": "#3a3a3f",
        }
    return {
        "page_bg": "#eef1f6",
        "card_bg": "#ffffff",
        "card_border": "#c8d0dc",
        "input_bg": "#f8fafc",
        "input_bg_hover": "#ffffff",
        "input_bg_focus": "#ffffff",
        "input_border": "#b8c4d4",
        "input_border_hover": "#8fa3b8",
        "accent": "#0078D4",
        "btn_secondary_bg": "#eef2f7",
        "btn_secondary_hover": "#e2e9f3",
        "btn_secondary_border": "#b8c4d4",
        "tab_inactive": "#e4e9f0",
        "segmented_track": "#e8ecf2",
        "muted_text": "#5f6b7a",
        "drop_bg": "#f6f8fb",
        "drop_border": "#a8b4c4",
        "drop_hover_bg": "rgba(0, 120, 212, 0.08)",
        "tool_btn_bg": "#eef2f7",
        "tool_btn_hover": "#dce6f2",
    }


def build_supplement_stylesheet(dark: bool | None = None) -> str:
    c = palette(dark)
    return f"""
{STYLE_MARKER}
/* ── 页面底色 ── */
ScrollArea[objectName$="Page"],
QWidget[objectName$="Page"] {{
    background-color: {c['page_bg']};
}}

/* ── 参数卡片 ── */
CardWidget {{
    background-color: {c['card_bg']};
    border: 1px solid {c['card_border']};
    border-radius: 10px;
}}

/* ── 文本输入 ── */
LineEdit, QLineEdit, TextEdit, QPlainTextEdit {{
    background-color: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {c['accent']};
}}
LineEdit:hover, QLineEdit:hover, TextEdit:hover, QPlainTextEdit:hover {{
    background-color: {c['input_bg_hover']};
    border-color: {c['input_border_hover']};
}}
LineEdit:focus, QLineEdit:focus, TextEdit:focus, QPlainTextEdit:focus {{
    background-color: {c['input_bg_focus']};
    border-color: {c['accent']};
}}

/* ── 数字输入 ── */
SpinBox, QSpinBox, DoubleSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: 6px;
    padding: 2px 6px;
    min-height: 28px;
}}
SpinBox:hover, QSpinBox:hover, DoubleSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {c['input_border_hover']};
    background-color: {c['input_bg_hover']};
}}
SpinBox:focus, QSpinBox:focus, DoubleSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}

/* ── 下拉框 ── */
ComboBox, QComboBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: 6px;
    padding: 2px 8px;
    min-height: 28px;
}}
ComboBox:hover, QComboBox:hover {{
    background-color: {c['input_bg_hover']};
    border-color: {c['input_border_hover']};
}}

/* ── 次要按钮（主按钮由 Fluent 自绘） ── */
PushButton {{
    background-color: {c['btn_secondary_bg']};
    border: 1px solid {c['btn_secondary_border']};
    border-radius: 6px;
    padding: 5px 14px;
    min-height: 28px;
}}
PushButton:hover {{
    background-color: {c['btn_secondary_hover']};
    border-color: {c['accent']};
}}
PushButton:pressed {{
    background-color: {c['input_border']};
}}

/* ── 图标小按钮 ── */
ToolButton {{
    background-color: {c['tool_btn_bg']};
    border: 1px solid {c['btn_secondary_border']};
    border-radius: 6px;
}}
ToolButton:hover {{
    background-color: {c['tool_btn_hover']};
    border-color: {c['accent']};
}}

/* ── 分段选择器底轨 ── */
SegmentedWidget, Pivot {{
    background-color: {c['segmented_track']};
    border: 1px solid {c['card_border']};
    border-radius: 8px;
    padding: 3px;
}}

/* ── 选项卡 ── */
QTabWidget::pane {{
    border: 1px solid {c['card_border']};
    border-radius: 8px;
    background: {c['card_bg']};
    top: -1px;
    padding: 4px;
}}
QTabBar::tab {{
    background: {c['tab_inactive']};
    border: 1px solid {c['card_border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 16px;
    margin-right: 3px;
    min-width: 72px;
}}
QTabBar::tab:selected {{
    background: {c['card_bg']};
    border-color: {c['accent']};
    color: {c['accent']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {c['input_bg_hover']};
}}

/* ── 辅助说明文字 ── */
CaptionLabel {{
    color: {c['muted_text']};
}}

/* ── 滑块轨道 ── */
QSlider::groove:horizontal {{
    background: {c['segmented_track']};
    border: 1px solid {c['input_border']};
    border-radius: 3px;
    height: 6px;
}}
"""


def drop_zone_stylesheet(*, hover: bool = False, dark: bool | None = None) -> str:
    c = palette(dark)
    if hover:
        return f"""
            #dropZone {{
                border: 2px dashed {c['accent']};
                border-radius: 10px;
                background: {c['drop_hover_bg']};
            }}
        """
    return f"""
        #dropZone {{
            border: 2px dashed {c['drop_border']};
            border-radius: 10px;
            background: {c['drop_bg']};
        }}
        #dropZone:hover {{
            border-color: {c['accent']};
            background: {c['drop_hover_bg']};
        }}
    """


def apply_app_styles(app: QApplication | None = None) -> None:
    """应用/刷新全局补充样式（主题切换后需再次调用）。"""
    app = app or QApplication.instance()
    if app is None:
        return
    existing = app.styleSheet() or ""
    if STYLE_MARKER in existing:
        existing = existing[: existing.index(STYLE_MARKER)].rstrip()
    app.setStyleSheet(existing + "\n" + build_supplement_stylesheet())
