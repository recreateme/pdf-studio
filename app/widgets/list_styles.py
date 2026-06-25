"""
PDF Studio - 列表与内容面板统一样式（浅色/深色自适应）
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QListWidget
from qfluentwidgets import isDarkTheme


def _resolve_dark(dark: bool | None) -> bool:
    return isDarkTheme() if dark is None else dark


def list_widget_stylesheet(*, dark: bool | None = None) -> str:
    """QListWidget 统一样式：列表区背景、条目边框、选中高亮。"""
    if _resolve_dark(dark):
        return """
            QListWidget {
                background: #252526;
                border: 1px solid #454545;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 10px;
                margin: 2px 0px;
                border: 1px solid #404040;
                border-radius: 6px;
                background: #2d2d30;
                color: #ececec;
            }
            QListWidget::item:selected {
                background: #0c3b5e;
                border: 1px solid #60CDFF;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background: #35353a;
                border: 1px solid #5a5a5a;
            }
            QListWidget::item:selected:hover {
                background: #0f4770;
                border: 1px solid #79d4ff;
            }
        """
    return """
        QListWidget {
            background: #f3f4f6;
            border: 1px solid #c8ced6;
            border-radius: 8px;
            padding: 4px;
            outline: none;
        }
        QListWidget::item {
            padding: 8px 10px;
            margin: 2px 0px;
            border: 1px solid #d8dee6;
            border-radius: 6px;
            background: #ffffff;
            color: #1f2937;
        }
        QListWidget::item:selected {
            background: #e8f3fc;
            border: 1px solid #0078D4;
            color: #0b3d6d;
        }
        QListWidget::item:hover {
            background: #f9fafb;
            border: 1px solid #b8c0cc;
        }
        QListWidget::item:selected:hover {
            background: #dceeff;
            border: 1px solid #106ebe;
        }
    """


def content_panel_stylesheet(*, dark: bool | None = None, placeholder: bool = False) -> str:
    """预览区 / 占位面板样式。"""
    if _resolve_dark(dark):
        if placeholder:
            return """
                QLabel {
                    color: #9ca3af;
                    background: #252526;
                    border: 1px dashed #555555;
                    border-radius: 8px;
                    padding: 12px;
                }
            """
        return """
            QLabel {
                color: #d1d5db;
                background: #1e1e1e;
                border: 1px solid #454545;
                border-radius: 8px;
                padding: 8px;
            }
        """
    if placeholder:
        return """
            QLabel {
                color: #6b7280;
                background: #f9fafb;
                border: 1px dashed #c8ced6;
                border-radius: 8px;
                padding: 12px;
            }
        """
    return """
        QLabel {
            color: #374151;
            background: #ffffff;
            border: 1px solid #c8ced6;
            border-radius: 8px;
            padding: 8px;
        }
    """


def apply_list_widget_style(widget: QListWidget, *, dark: bool | None = None) -> None:
    widget.setStyleSheet(list_widget_stylesheet(dark=dark))
    widget.setSpacing(2)


def apply_content_panel_style(
    label: QLabel,
    *,
    dark: bool | None = None,
    placeholder: bool = False,
) -> None:
    label.setStyleSheet(content_panel_stylesheet(dark=dark, placeholder=placeholder))
