"""
PDF Studio - 可拖拽排序的图片文件列表（用于图片合并）
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QLabel,
)
from qfluentwidgets import CaptionLabel, PushButton, ToolButton, FluentIcon

from app.utils.helpers import get_file_size_str, open_file
from app.widgets.list_styles import apply_content_panel_style, apply_list_widget_style


def _thumbnail_png_bytes(img) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class ImageMergeList(QWidget):
    """文件列表 + 选中项大图预览；支持拖拽排序"""

    changed = pyqtSignal()

    LIST_ICON_SIZE = 28
    PREVIEW_ABSOLUTE_MAX = 4096

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.ListMode)
        self._list.setIconSize(QSize(self.LIST_ICON_SIZE, self.LIST_ICON_SIZE))
        self._list.setMovement(QListWidget.Movement.Snap)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        apply_list_widget_style(self._list)
        self._list.model().rowsMoved.connect(lambda *_: self._emit_changed())
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 2)

        self._preview_label = QLabel("单击列表项查看大图，双击用系统默认程序打开")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(180)
        self._preview_label.setScaledContents(False)
        apply_content_panel_style(self._preview_label, placeholder=True)
        layout.addWidget(self._preview_label, 3)

        btn_row = QHBoxLayout()
        self._count_label = CaptionLabel("共 0 张图片")
        up_btn = ToolButton(FluentIcon.UP)
        up_btn.setToolTip("上移")
        up_btn.clicked.connect(self._move_up)
        down_btn = ToolButton(FluentIcon.DOWN)
        down_btn.setToolTip("下移")
        down_btn.clicked.connect(self._move_down)
        del_btn = ToolButton(FluentIcon.DELETE)
        del_btn.setToolTip("删除选中")
        del_btn.clicked.connect(self.remove_selected)
        clear_btn = PushButton("清空")
        clear_btn.setFixedWidth(64)
        clear_btn.clicked.connect(self.clear)
        btn_row.addWidget(self._count_label)
        btn_row.addStretch()
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def _preview_pixel_budget(self) -> tuple[int, int]:
        """按预览区实际尺寸与 DPI 计算目标像素，避免过度缩小。"""
        dpr = max(self.devicePixelRatioF(), 1.0)
        max_w = max(int((self._preview_label.width() - 16) * dpr), 320)
        max_h = max(int((self._preview_label.height() - 16) * dpr), 240)
        max_w = min(max_w, self.PREVIEW_ABSOLUTE_MAX)
        max_h = min(max_h, self.PREVIEW_ABSOLUTE_MAX)
        return max_w, max_h

    def _emit_changed(self) -> None:
        self._update_count()
        self.changed.emit()

    def _update_count(self) -> None:
        self._count_label.setText(f"共 {self._list.count()} 张图片（拖拽可调序）")

    def _make_list_icon(self, path: str) -> QIcon:
        try:
            from PIL import Image

            with Image.open(path) as img:
                if getattr(img, "is_animated", False):
                    img.seek(0)
                img = img.convert("RGB")
                img.thumbnail(
                    (self.LIST_ICON_SIZE, self.LIST_ICON_SIZE),
                    Image.Resampling.LANCZOS,
                )
                buf = _thumbnail_png_bytes(img)
            pix = QPixmap()
            pix.loadFromData(buf, "PNG")
            return QIcon(pix)
        except Exception:
            return QIcon()

    def _make_preview_pixmap(self, path: str, max_w: int, max_h: int) -> QPixmap | None:
        pix = QPixmap(path)
        if not pix.isNull():
            if pix.width() > max_w or pix.height() > max_h:
                pix = pix.scaled(
                    max_w, max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return pix

        try:
            from PIL import Image

            with Image.open(path) as img:
                if getattr(img, "is_animated", False):
                    img.seek(0)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                if img.width > max_w or img.height > max_h:
                    img = img.copy()
                    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                buf = _thumbnail_png_bytes(img)
            fallback = QPixmap()
            if fallback.loadFromData(buf, "PNG"):
                return fallback
        except Exception:
            pass
        return None

    def _show_preview(self, path: str) -> None:
        self._current_path = path
        if not path:
            apply_content_panel_style(self._preview_label, placeholder=True)
            self._preview_label.setText("单击列表项查看大图，双击用系统默认程序打开")
            self._preview_label.setPixmap(QPixmap())
            return

        max_w, max_h = self._preview_pixel_budget()
        pix = self._make_preview_pixmap(path, max_w, max_h)
        if pix is None or pix.isNull():
            self._preview_label.setPixmap(QPixmap())
            apply_content_panel_style(self._preview_label, placeholder=True)
            self._preview_label.setText(f"无法预览：{Path(path).name}")
            return

        self._preview_label.setText("")
        apply_content_panel_style(self._preview_label, placeholder=False)
        self._preview_label.setPixmap(pix)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_list_widget_style(self._list)
        apply_content_panel_style(
            self._preview_label,
            placeholder=not bool(self._current_path),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_path:
            self._show_preview(self._current_path)

    def _on_current_item_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._show_preview("")
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        self._show_preview(path if isinstance(path, str) else "")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and isinstance(path, str) and Path(path).is_file():
            open_file(path)

    def add_files(self, paths: list[str]) -> int:
        existing = set(self.get_paths())
        added = 0
        for p in paths:
            if p in existing or not Path(p).is_file():
                continue
            name = Path(p).name
            size_str = get_file_size_str(p)
            item = QListWidgetItem(f"{name}  ({size_str})")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            item.setIcon(self._make_list_icon(p))
            self._list.addItem(item)
            existing.add(p)
            added += 1
        if added and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        self._emit_changed()
        return added

    def get_paths(self) -> list[str]:
        paths: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            p = item.data(Qt.ItemDataRole.UserRole)
            if p and isinstance(p, str):
                paths.append(p)
        return paths

    def clear(self) -> None:
        self._list.clear()
        self._show_preview("")
        self._emit_changed()

    def remove_selected(self) -> None:
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
        if self._list.count() == 0:
            self._show_preview("")
        self._emit_changed()

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row <= 0:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row - 1, item)
        self._list.setCurrentRow(row - 1)
        self._emit_changed()

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= self._list.count() - 1:
            return
        item = self._list.takeItem(row)
        self._list.insertItem(row + 1, item)
        self._list.setCurrentRow(row + 1)
        self._emit_changed()
