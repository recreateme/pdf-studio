"""
PDF Studio - 单页渲染与区域选择控件
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import QLabel, QSizePolicy

from app.utils.logger import logger

OverlayMeta = dict[str, Any]
OverlayItem = tuple[tuple[float, float, float, float], str, OverlayMeta]


class PDFPageView(QLabel):
    """显示单页 PNG，批注模式下支持框选 / 手绘 / 点击放置"""

    regionSelected = pyqtSignal(int, float, float, float, float)
    pageClicked = pyqtSignal(int, float, float)
    inkDrawn = pyqtSignal(int, list)
    noteClicked = pyqtSignal(int, str, int)
    freetextResized = pyqtSignal(int, int, float, float, float, float)

    RECT_TOOLS = frozenset({"highlight", "underline", "strikeout", "rect", "line"})
    TEXT_SNAP_TOOLS = frozenset({"highlight", "underline", "strikeout"})

    def __init__(self, page_index: int, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self._pdf_width = 1.0
        self._pdf_height = 1.0
        self._annotate_mode = False
        self._tool = "highlight"
        self._drag_start: Optional[QPoint] = None
        self._drag_rect: Optional[QRect] = None
        self._ink_points: list[tuple[float, float]] = []
        self._overlay_items: list[OverlayItem] = []
        self._overlay_paths: list[tuple[list[tuple[float, float, float, float]], str]] = []
        self._resize_pending_idx: Optional[int] = None
        self._resize_origin: Optional[tuple[float, float, float, float]] = None

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.apply_reader_theme(False)
        self.setMinimumHeight(120)

    def apply_reader_theme(self, dark: bool) -> None:
        bg = "#2d2d2d" if dark else "#e8e8e8"
        self.setStyleSheet(f"background: {bg}; border-radius: 4px; margin: 4px 0;")

    def has_pixmap(self) -> bool:
        pix = self.pixmap()
        return pix is not None and not pix.isNull()

    def set_page_pixmap(
        self,
        png_bytes: bytes,
        pdf_width: float,
        pdf_height: float,
    ) -> None:
        pix = QPixmap()
        if not png_bytes:
            return
        if not pix.loadFromData(png_bytes, "PNG"):
            logger.warning(f"页 {self.page_index + 1} 图像加载失败")
            return
        self._pdf_width = pdf_width or 1.0
        self._pdf_height = pdf_height or 1.0
        self.setPixmap(pix)
        self.setFixedHeight(pix.height() + 8)
        self.update()

    def clear_page_pixmap(self, placeholder_height: int = 720) -> None:
        self.setPixmap(QPixmap())
        self.setFixedHeight(placeholder_height)
        self.update()

    def set_annotate_mode(self, enabled: bool, tool: str = "highlight") -> None:
        self._annotate_mode = enabled
        self._tool = tool
        if enabled and self._tool == "ink":
            cursor = Qt.CursorShape.PointingHandCursor
        elif enabled:
            cursor = Qt.CursorShape.CrossCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    def set_overlay_rects(
        self,
        items: list[OverlayItem],
        paths: Optional[list[tuple[list[tuple[float, float, float, float]], str]]] = None,
    ) -> None:
        """临时 overlay: [(pdf_rect, kind, meta), ...] 与手绘路径"""
        self._overlay_items = items
        self._overlay_paths = paths or []
        self.update()

    def _pixmap_rect(self) -> QRect:
        if self.pixmap() is None or self.pixmap().isNull():
            return QRect()
        pw = self.pixmap().width()
        ph = self.pixmap().height()
        x = max(0, (self.width() - pw) // 2)
        y = max(0, (self.height() - ph) // 2)
        return QRect(x, y, pw, ph)

    def _widget_to_pdf(self, pos: QPoint) -> tuple[float, float]:
        pr = self._pixmap_rect()
        if pr.isEmpty():
            return 0.0, 0.0
        rel_x = max(0.0, min(1.0, (pos.x() - pr.x()) / pr.width()))
        rel_y = max(0.0, min(1.0, (pos.y() - pr.y()) / pr.height()))
        return rel_x * self._pdf_width, rel_y * self._pdf_height

    def _pdf_point_to_widget(self, px: float, py: float) -> QPoint:
        pr = self._pixmap_rect()
        if pr.isEmpty():
            return QPoint()
        sx = pr.width() / self._pdf_width
        sy = pr.height() / self._pdf_height
        return QPoint(int(pr.x() + px * sx), int(pr.y() + py * sy))

    def _pdf_rect_to_widget(self, rect: tuple[float, float, float, float]) -> QRect:
        pr = self._pixmap_rect()
        if pr.isEmpty():
            return QRect()
        x0, y0, x1, y1 = rect
        sx = pr.width() / self._pdf_width
        sy = pr.height() / self._pdf_height
        return QRect(
            int(pr.x() + x0 * sx),
            int(pr.y() + y0 * sy),
            int(max(1, (x1 - x0) * sx)),
            int(max(1, (y1 - y0) * sy)),
        )

    def _hit_overlay(self, pos: QPoint) -> Optional[OverlayItem]:
        for rect, kind, meta in reversed(self._overlay_items):
            wr = self._pdf_rect_to_widget(rect)
            if wr.contains(pos):
                return (rect, kind, meta)
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        hit = self._hit_overlay(event.pos())
        if hit is not None:
            rect, kind, meta = hit
            if kind == "note":
                self.noteClicked.emit(
                    self.page_index,
                    str(meta.get("content", "")),
                    int(meta.get("pending_idx", -1)),
                )
                return
            if (
                self._annotate_mode
                and self._tool == "freetext"
                and kind == "freetext"
                and meta.get("pending_idx") is not None
            ):
                self._resize_pending_idx = int(meta["pending_idx"])
                self._resize_origin = rect
                return

        if not self._annotate_mode:
            super().mousePressEvent(event)
            return

        pr = self._pixmap_rect()
        if self._tool in ("freetext", "note", "stamp"):
            px, py = self._widget_to_pdf(event.pos())
            self.pageClicked.emit(self.page_index, px, py)
            return
        if self._tool == "ink":
            px, py = self._widget_to_pdf(event.pos())
            self._ink_points = [(px, py)]
            self.update()
            return
        if self._tool in self.RECT_TOOLS:
            if not pr.contains(event.pos()):
                return
            self._drag_start = event.pos()
            self._drag_rect = QRect(self._drag_start, self._drag_start)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._resize_pending_idx is not None and self._resize_origin is not None:
            x0, y0, _, _ = self._resize_origin
            px, py = self._widget_to_pdf(event.pos())
            min_w, min_h = 40.0, 24.0
            x1 = max(x0 + min_w, px)
            y1 = max(y0 + min_h, py)
            self._overlay_items = [
                (rect, kind, meta)
                if not (
                    kind == "freetext"
                    and meta.get("pending_idx") == self._resize_pending_idx
                )
                else ((x0, y0, x1, y1), kind, meta)
                for rect, kind, meta in self._overlay_items
            ]
            self.update()
        elif self._tool == "ink" and self._ink_points:
            px, py = self._widget_to_pdf(event.pos())
            self._ink_points.append((px, py))
            self.update()
        elif self._drag_start is not None:
            self._drag_rect = QRect(self._drag_start, event.pos()).normalized()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._resize_pending_idx is not None
            and self._resize_origin is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            for rect, kind, meta in self._overlay_items:
                if (
                    kind == "freetext"
                    and meta.get("pending_idx") == self._resize_pending_idx
                ):
                    self.freetextResized.emit(
                        self.page_index,
                        self._resize_pending_idx,
                        rect[0], rect[1], rect[2], rect[3],
                    )
                    break
            self._resize_pending_idx = None
            self._resize_origin = None
            self.update()
        elif self._tool == "ink" and self._ink_points and event.button() == Qt.MouseButton.LeftButton:
            if len(self._ink_points) >= 2:
                self.inkDrawn.emit(self.page_index, list(self._ink_points))
            self._ink_points = []
            self.update()
        elif self._drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            if self._drag_rect and self._drag_rect.width() > 4 and self._drag_rect.height() > 4:
                pr = self._pixmap_rect()
                r = self._drag_rect.intersected(pr)
                if r.width() > 2 and r.height() > 2:
                    tl = self._widget_to_pdf(r.topLeft())
                    br = self._widget_to_pdf(r.bottomRight())
                    x0, y0 = tl
                    x1, y1 = br
                    if x1 < x0:
                        x0, x1 = x1, x0
                    if y1 < y0:
                        y0, y1 = y1, y0
                    self.regionSelected.emit(self.page_index, x0, y0, x1, y1)
            self._drag_start = None
            self._drag_rect = None
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for rect, kind, _meta in self._overlay_items:
            wr = self._pdf_rect_to_widget(rect)
            if kind == "highlight":
                painter.fillRect(wr, QColor(255, 255, 0, 90))
            elif kind == "underline":
                pen = QPen(QColor(255, 0, 0, 200), 2)
                painter.setPen(pen)
                painter.drawLine(wr.bottomLeft(), wr.bottomRight())
            elif kind == "strikeout":
                pen = QPen(QColor(200, 0, 0, 220), 2)
                painter.setPen(pen)
                mid = wr.center().y()
                painter.drawLine(wr.left(), mid, wr.right(), mid)
            elif kind == "search":
                painter.fillRect(wr, QColor(0, 120, 215, 70))
                pen = QPen(QColor(0, 90, 180, 240), 2)
                painter.setPen(pen)
                painter.drawRect(wr)
            elif kind == "search_dim":
                painter.fillRect(wr, QColor(0, 120, 215, 35))
                pen = QPen(QColor(0, 120, 215, 100), 1)
                painter.setPen(pen)
                painter.drawRect(wr)
            elif kind == "freetext":
                pen = QPen(QColor(255, 140, 0, 200), 2)
                painter.setPen(pen)
                painter.drawRect(wr)
                if (
                    self._annotate_mode
                    and self._tool == "freetext"
                    and _meta.get("pending_idx") is not None
                ):
                    handle = QRect(wr.right() - 8, wr.bottom() - 8, 8, 8)
                    painter.fillRect(handle, QColor(255, 140, 0, 180))
            elif kind == "note":
                pen = QPen(QColor(255, 200, 0, 230), 2)
                painter.setBrush(QColor(255, 255, 120, 200))
                painter.setPen(pen)
                painter.drawRect(wr.x(), wr.y(), 18, 18)
            elif kind == "stamp":
                pen = QPen(QColor(180, 0, 0, 200), 2)
                painter.setPen(pen)
                painter.drawRect(wr)
            elif kind in ("rect", "line"):
                pen = QPen(QColor(0, 100, 255, 200), 2)
                painter.setPen(pen)
                if kind == "line":
                    painter.drawLine(wr.topLeft(), wr.bottomRight())
                else:
                    painter.drawRect(wr)

        for points, _kind in self._overlay_paths:
            if len(points) < 2:
                continue
            pen = QPen(QColor(0, 80, 255, 220), 2)
            painter.setPen(pen)
            widget_pts = [self._pdf_point_to_widget(x, y) for x, y in points]
            for i in range(len(widget_pts) - 1):
                painter.drawLine(widget_pts[i], widget_pts[i + 1])

        if self._ink_points and len(self._ink_points) >= 2:
            pen = QPen(QColor(0, 80, 255, 220), 2)
            painter.setPen(pen)
            widget_pts = [self._pdf_point_to_widget(x, y) for x, y in self._ink_points]
            for i in range(len(widget_pts) - 1):
                painter.drawLine(widget_pts[i], widget_pts[i + 1])

        if self._drag_rect is not None:
            pen = QPen(QColor(0, 120, 215), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.fillRect(self._drag_rect, QColor(0, 120, 215, 40))
            painter.drawRect(self._drag_rect)

        painter.end()
