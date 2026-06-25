"""
PDF Studio - 通用 UI 小组件
共享控件：拖放区域、进度卡片、缩略图格、Toast通知等
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    Qt, QMimeData, QSize, QTimer,
    pyqtSignal, QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent,
    QPixmap, QPainter, QFont, QIcon,
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy, QGraphicsOpacityEffect,
    QScrollArea, QGridLayout, QProgressBar,
    QApplication,
)
from qfluentwidgets import (
    CardWidget, ProgressBar, IconWidget,
    FluentIcon, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton,
    InfoBar, InfoBarPosition,
    FlowLayout,
)

from app.config.constants import (
    SUPPORTED_PDF_EXTENSIONS, SUPPORTED_IMAGE_EXTENSIONS,
    get_thumbnail_width, get_thumbnail_height,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO,
)
from app.ui.app_styles import drop_zone_stylesheet


# ─────────────────────────────────────────────
# 拖放文件区域
# ─────────────────────────────────────────────

class DropZone(QFrame):
    """
    文件拖放接收区域
    支持 PDF 和图片文件，拖入时显示高亮效果
    """

    filesDropped = pyqtSignal(list)    # 信号：文件列表 [str]

    def __init__(
        self,
        accept_types: str = "pdf",     # "pdf" / "image" / "all"
        hint_text: str = "拖放文件到此处，或点击选择",
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._accept_types = accept_types
        self._hint_text = hint_text
        self._is_hover = False
        self._setup_ui()
        self.setAcceptDrops(True)

    def _get_accept_extensions(self) -> set[str]:
        if self._accept_types == "pdf":
            return SUPPORTED_PDF_EXTENSIONS
        if self._accept_types == "image":
            return SUPPORTED_IMAGE_EXTENSIONS
        return SUPPORTED_PDF_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS

    def _setup_ui(self) -> None:
        self.setObjectName("dropZone")
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        # 图标
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedSize(48, 48)

        # 主提示
        self._hint_label = BodyLabel(self._hint_text)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 副提示
        ext_str = ", ".join(sorted(self._get_accept_extensions()))
        self._sub_label = CaptionLabel(f"支持格式：{ext_str}")
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._icon_label)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._sub_label)

        self._update_style(False)

    def _update_style(self, hover: bool) -> None:
        self.setStyleSheet(drop_zone_stylesheet(hover=hover))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_style(self._is_hover)

    # ── 拖放事件 ──────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls()]
            exts = self._get_accept_extensions()
            if any(Path(p).suffix.lower() in exts for p in paths):
                event.acceptProposedAction()
                self._is_hover = True
                self._update_style(True)
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._is_hover = False
        self._update_style(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._is_hover = False
        self._update_style(False)
        exts = self._get_accept_extensions()
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if Path(u.toLocalFile()).suffix.lower() in exts
        ]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:
        """点击时打开文件选择对话框"""
        from PyQt6.QtWidgets import QFileDialog
        exts = self._get_accept_extensions()
        filter_str = "支持的文件 (" + " ".join(f"*{e}" for e in sorted(exts)) + ")"
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "", filter_str
        )
        if files:
            self.filesDropped.emit(files)


# ─────────────────────────────────────────────
# PDF 缩略图卡片
# ─────────────────────────────────────────────

class ThumbnailCard(QFrame):
    """
    单页缩略图卡片
    显示页码、缩略图，支持选中状态
    """

    clicked = pyqtSignal(int)           # 信号：页码(0-based)
    doubleClicked = pyqtSignal(int)

    def __init__(self, page_index: int, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self._selected = False
        self._pixmap: Optional[QPixmap] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        thumb_w = get_thumbnail_width()
        thumb_h = get_thumbnail_height()
        self.setFixedSize(thumb_w + 16, thumb_h + 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        # 缩略图显示区
        self._img_label = QLabel()
        self._img_label.setFixedSize(thumb_w, thumb_h)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("background: #f5f5f5; border-radius: 4px;")

        # 页码标签
        self._page_label = CaptionLabel(f"第 {self.page_index + 1} 页")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._img_label)
        layout.addWidget(self._page_label)

        self._update_style()

    def set_thumbnail(self, png_bytes: bytes) -> None:
        """设置缩略图数据（PNG字节）"""
        thumb_w = get_thumbnail_width()
        thumb_h = get_thumbnail_height()
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)
        self._pixmap = pixmap
        scaled = pixmap.scaled(
            thumb_w, thumb_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img_label.setPixmap(scaled)

    def set_loading(self) -> None:
        """显示加载中状态"""
        self._img_label.setText("加载中...")
        self._img_label.setStyleSheet(
            "background: #eeeeee; border-radius: 4px; color: #999;"
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def is_selected(self) -> bool:
        return self._selected

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet("""
                ThumbnailCard {
                    border: 2px solid #0078D4;
                    border-radius: 8px;
                    background: rgba(0,120,212,0.1);
                }
            """)
        else:
            self.setStyleSheet("""
                ThumbnailCard {
                    border: 1px solid rgba(128,128,128,0.2);
                    border-radius: 8px;
                    background: transparent;
                }
                ThumbnailCard:hover {
                    border-color: #0078D4;
                    background: rgba(0,120,212,0.05);
                }
            """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.page_index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit(self.page_index)
        super().mouseDoubleClickEvent(event)


# ─────────────────────────────────────────────
# 缩略图滚动面板
# ─────────────────────────────────────────────

class ThumbnailPanel(QScrollArea):
    """
    可滚动的缩略图面板
    支持多选（Ctrl+点击/Shift+点击）
    """

    selectionChanged = pyqtSignal(list)   # 信号：选中的页码列表(0-based)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._cards: dict[int, ThumbnailCard] = {}
        self._selected: set[int] = set()
        self._last_clicked: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        self._flow = FlowLayout(container, needAni=False)
        self._flow.setContentsMargins(8, 8, 8, 8)
        self._flow.setSpacing(8)
        self.setWidget(container)

    def add_page(self, page_index: int) -> ThumbnailCard:
        """添加一个页面卡片"""
        card = ThumbnailCard(page_index)
        card.set_loading()
        card.clicked.connect(self._on_card_clicked)
        self._cards[page_index] = card
        self._flow.addWidget(card)
        return card

    def get_card(self, page_index: int) -> Optional[ThumbnailCard]:
        return self._cards.get(page_index)

    def clear(self) -> None:
        """清空所有卡片"""
        for card in self._cards.values():
            self._flow.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._selected.clear()
        self._last_clicked = -1

    def get_selected(self) -> list[int]:
        return sorted(self._selected)

    def select_all(self) -> None:
        for idx in self._cards:
            self._selected.add(idx)
            self._cards[idx].set_selected(True)
        self.selectionChanged.emit(self.get_selected())

    def deselect_all(self) -> None:
        for idx in self._selected:
            if idx in self._cards:
                self._cards[idx].set_selected(False)
        self._selected.clear()
        self.selectionChanged.emit([])

    def select_indices(self, indices: list[int]) -> None:
        self.deselect_all()
        for idx in indices:
            if idx in self._cards:
                self._selected.add(idx)
                self._cards[idx].set_selected(True)
        self.selectionChanged.emit(self.get_selected())

    def select_odd_pages(self) -> None:
        """选中奇数页（第 1、3、5… 页）"""
        self.select_indices([i for i in self._cards if i % 2 == 0])

    def select_even_pages(self) -> None:
        """选中偶数页（第 2、4、6… 页）"""
        self.select_indices([i for i in self._cards if i % 2 == 1])

    def _on_card_clicked(self, page_index: int) -> None:
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+点击：切换单个选中
            if page_index in self._selected:
                self._selected.discard(page_index)
                self._cards[page_index].set_selected(False)
            else:
                self._selected.add(page_index)
                self._cards[page_index].set_selected(True)

        elif modifiers & Qt.KeyboardModifier.ShiftModifier and self._last_clicked >= 0:
            # Shift+点击：范围选择
            start = min(self._last_clicked, page_index)
            end = max(self._last_clicked, page_index)
            for idx in range(start, end + 1):
                if idx in self._cards:
                    self._selected.add(idx)
                    self._cards[idx].set_selected(True)

        else:
            # 普通点击：单选
            for idx in list(self._selected):
                if idx in self._cards:
                    self._cards[idx].set_selected(False)
            self._selected = {page_index}
            self._cards[page_index].set_selected(True)

        self._last_clicked = page_index
        self.selectionChanged.emit(self.get_selected())


# ─────────────────────────────────────────────
# 任务进度卡片
# ─────────────────────────────────────────────

class TaskProgressCard(CardWidget):
    """
    单个任务进度显示卡片
    显示文件名、进度条、状态、耗时
    """

    cancelRequested = pyqtSignal()

    def __init__(self, title: str, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._setup_ui(title)

    def _setup_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        self._title_label = BodyLabel(title)
        self._status_label = CaptionLabel("等待中")
        self._status_label.setStyleSheet("color: #999;")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        title_row.addWidget(self._status_label)

        # 进度条
        self._progress = ProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

        # 消息行
        msg_row = QHBoxLayout()
        self._msg_label = CaptionLabel("")
        self._msg_label.setStyleSheet("color: #666;")
        self._cancel_btn = PushButton("取消")
        self._cancel_btn.setFixedWidth(60)
        self._cancel_btn.clicked.connect(self.cancelRequested.emit)
        msg_row.addWidget(self._msg_label)
        msg_row.addStretch()
        msg_row.addWidget(self._cancel_btn)

        layout.addLayout(title_row)
        layout.addWidget(self._progress)
        layout.addLayout(msg_row)

    def update_progress(self, current: int, total: int) -> None:
        pct = int(current * 100 / max(total, 1))
        self._progress.setValue(pct)
        self._status_label.setText(f"{current}/{total}")

    def set_message(self, msg: str) -> None:
        self._msg_label.setText(msg)

    def set_status(self, status: str, color: str = "#666") -> None:
        self._status_label.setText(status)
        self._status_label.setStyleSheet(f"color: {color};")

    def set_finished(self, success: bool, msg: str = "") -> None:
        self._progress.setValue(100)
        self._cancel_btn.setEnabled(False)
        if success:
            self.set_status("完成", COLOR_SUCCESS)
        else:
            self.set_status("失败", COLOR_ERROR)
        if msg:
            self._msg_label.setText(msg)

    def set_cancelled(self) -> None:
        self._cancel_btn.setEnabled(False)
        self.set_status("已取消", COLOR_WARNING)


# ─────────────────────────────────────────────
# Toast 通知工具函数
# ─────────────────────────────────────────────

def show_success(parent: QWidget, title: str, content: str = "") -> None:
    InfoBar.success(title, content, parent=parent, position=InfoBarPosition.TOP_RIGHT, duration=3000)


def show_error(parent: QWidget, title: str, content: str = "") -> None:
    InfoBar.error(title, content, parent=parent, position=InfoBarPosition.TOP_RIGHT, duration=5000)


def show_warning(parent: QWidget, title: str, content: str = "") -> None:
    InfoBar.warning(title, content, parent=parent, position=InfoBarPosition.TOP_RIGHT, duration=4000)


def show_info(parent: QWidget, title: str, content: str = "") -> None:
    InfoBar.info(title, content, parent=parent, position=InfoBarPosition.TOP_RIGHT, duration=3000)


def wps_hint_label(key: str) -> CaptionLabel:
    """功能页 WPS 对标旁注"""
    from app.config.constants import PAGE_WPS_HINTS
    text = PAGE_WPS_HINTS.get(key, "")
    lbl = CaptionLabel(text)
    lbl.setStyleSheet("color: #0078D4;")
    return lbl


def finish_output_task(
    parent: QWidget,
    title: str,
    output_path: str | Path,
    *,
    open_folder: bool = True,
) -> None:
    """任务完成：成功提示 + 打开目录 + WPS 查看引导"""
    from app.config.constants import OUTPUT_VIEW_HINT
    from app.utils.helpers import open_in_explorer

    p = Path(output_path)
    show_success(parent, title, f"{p.name}\n{OUTPUT_VIEW_HINT}")
    if not open_folder:
        return
    target = p if p.is_dir() else p.parent
    if target.exists():
        open_in_explorer(target)


# ─────────────────────────────────────────────
# 文件列表行
# ─────────────────────────────────────────────

class FileListItem(QFrame):
    """文件列表中的单行条目"""

    removeRequested = pyqtSignal(str)   # 携带文件路径
    moveUpRequested = pyqtSignal(str)
    moveDownRequested = pyqtSignal(str)

    def __init__(self, path: str, index: int, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.path = path
        self._setup_ui(path, index)

    def _setup_ui(self, path: str, index: int) -> None:
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(8)

        # 序号
        idx_label = CaptionLabel(f"{index + 1:02d}")
        idx_label.setFixedWidth(24)
        idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idx_label.setStyleSheet("color: #888;")

        # 文件名
        from app.utils.helpers import get_file_size_str
        p = Path(path)
        name_label = BodyLabel(p.name)
        name_label.setToolTip(path)

        try:
            size_str = get_file_size_str(path)
        except Exception:
            size_str = ""
        size_label = CaptionLabel(size_str)
        size_label.setStyleSheet("color: #888;")
        size_label.setFixedWidth(64)

        # 操作按钮
        up_btn = PushButton("↑")
        up_btn.setFixedSize(28, 28)
        up_btn.clicked.connect(lambda: self.moveUpRequested.emit(self.path))

        down_btn = PushButton("↓")
        down_btn.setFixedSize(28, 28)
        down_btn.clicked.connect(lambda: self.moveDownRequested.emit(self.path))

        del_btn = PushButton("×")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet("color: #C42B1C;")
        del_btn.clicked.connect(lambda: self.removeRequested.emit(self.path))

        layout.addWidget(idx_label)
        layout.addWidget(name_label, 1)
        layout.addWidget(size_label)
        layout.addWidget(up_btn)
        layout.addWidget(down_btn)
        layout.addWidget(del_btn)

    def update_index(self, index: int) -> None:
        # 更新序号（重排时调用）
        pass
