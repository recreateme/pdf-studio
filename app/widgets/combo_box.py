"""
PDF Studio - 统一下拉框
限制宽度、收紧下拉菜单外圈留白，避免 ComboBox 在布局中被拉成整行宽方块。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import QSizePolicy

from qfluentwidgets import ComboBox
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu


COMBO_HEIGHT = 33
COMBO_MIN_WIDTH = 120
COMBO_MAX_WIDTH = 320
# 与 qfluentwidgets combo_box.qss 左右 padding（11 + 31）及箭头区对齐
COMBO_H_PADDING = 52


class StudioComboBoxMenu(ComboBoxMenu):
    """下拉菜单：去掉 RoundMenu 外围留白，减轻阴影范围。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.setShadowEffect(
            blurRadius=16,
            offset=(0, 4),
            color=QColor(0, 0, 0, 35),
        )


class StudioComboBox(ComboBox):
    """内容自适应宽度的 ComboBox，不在布局中横向撑满。"""

    DEFAULT_WIDTH = 208

    def __init__(self, parent=None, *, width: int = 0):
        super().__init__(parent)
        self._preferred_width = width
        self.setFixedHeight(COMBO_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )

    def _createComboMenu(self):
        return StudioComboBoxMenu(self)

    def addItem(self, text, icon=None, userData=None):
        super().addItem(text, icon, userData)
        self._refresh_width()

    def addItems(self, texts):
        super().addItems(texts)
        self._refresh_width()

    def insertItem(self, index, text, icon=None, userData=None):
        super().insertItem(index, text, icon, userData)
        self._refresh_width()

    def _refresh_width(self) -> None:
        if self._preferred_width > 0:
            width = self._preferred_width
        elif not self.items:
            width = self.DEFAULT_WIDTH
        else:
            fm = QFontMetrics(self.font())
            max_text = max(item.text for item in self.items)
            width = fm.horizontalAdvance(max_text) + COMBO_H_PADDING
            width = max(COMBO_MIN_WIDTH, min(width, COMBO_MAX_WIDTH))
        self.setFixedWidth(width)
