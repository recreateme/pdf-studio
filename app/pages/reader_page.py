"""
PDF Studio - PDF 阅读与批注
轻量阅读器 + 高亮 / 下划线 / 文本框批注
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSplitter,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QInputDialog, QStackedWidget, QLineEdit, QButtonGroup, QMessageBox,
)
from qfluentwidgets import (
    ScrollArea, TitleLabel, CaptionLabel, PushButton, PrimaryPushButton,
    LineEdit, SpinBox, SegmentedWidget, StrongBodyLabel, FluentIcon,
    BodyLabel, ToolButton, isDarkTheme,
)

from app.config.constants import (
    READER_RENDER_BUFFER, READER_RENDER_CACHE_MAX, READER_ZOOM_WHEEL_STEP,
    READER_THUMB_BATCH, READER_PLACEHOLDER_HEIGHT, READER_DUAL_GAP,
    READER_LAYOUT_SPACING,
)
from app.config.settings import settings_mgr
from app.utils.helpers import get_file_size_str, open_in_explorer
from app.utils.render_cache import ReaderRenderCache
from app.widgets.common import (
    DropZone, show_success, show_error, show_warning, show_info,
    finish_output_task, wps_hint_label,
)
from app.widgets.pdf_page_view import PDFPageView
from app.widgets.combo_box import StudioComboBox
from app.widgets.list_styles import apply_list_widget_style
from app.workers.base_worker import (
    PDFPageRenderWorker, PDFSearchWorker, PDFSaveAnnotationsWorker,
    ThumbnailWorker, submit_worker,
)
from core.pdf.annotations import AnnotationItem, PDFAnnotationService, STAMP_NAMES
from core.pdf.processor import PDFReader as PDFReaderUtil
from core.pdf.viewer import (
    SearchHit, compute_reader_zoom, READER_ZOOM_MIN, READER_ZOOM_MAX,
    PDFViewerService,
)


class ReaderPage(ScrollArea):
    """PDF 阅读与批注"""

    ZOOM_PRESETS = {
        "50%": 0.5, "75%": 0.75, "100%": 1.0,
        "125%": 1.25, "150%": 1.5, "200%": 2.0,
    }
    TOOL_OPTIONS = [
        ("highlight", "高亮"),
        ("underline", "下划线"),
        ("strikeout", "删除线"),
        ("freetext", "文本框"),
        ("note", "便签"),
        ("ink", "自由绘制"),
        ("rect", "矩形"),
        ("line", "线条"),
        ("stamp", "图章"),
    ]
    ANNOT_FILTER_OPTIONS = ["全部", "高亮", "下划线", "删除线", "文本", "便签", "手绘", "形状", "图章"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("readerPage")
        self._pdf_path: Optional[str] = None
        self._password = ""
        self._page_count = 0
        self._zoom = 1.0
        self._fixed_zoom = 1.0
        self._fit_mode = "fit_width"
        self._layout_mode = "single"
        self._page_sizes: list[tuple[float, float]] = []
        self._max_page_width = 595.0
        self._max_page_height = 842.0
        self._fit_height_anchor = 0
        self._syncing_page_spin = False
        self._focus_mode = False
        self._pending_renders: set[int] = set()
        self._render_cache = ReaderRenderCache(READER_RENDER_CACHE_MAX)
        self._page_views: list[PDFPageView] = []
        self._layout_blocks: list[tuple[QWidget, list[int]]] = []
        self._thumb_png_cache: dict[int, bytes] = {}
        self._pending: list[AnnotationItem] = []
        self._existing: list[AnnotationItem] = []
        self._deleted_xrefs: set[int] = set()
        self._undo_stack: list[tuple[list[AnnotationItem], set[int]]] = []
        self._redo_stack: list[tuple[list[AnnotationItem], set[int]]] = []
        self._search_hits: list[SearchHit] = []
        self._search_index = -1
        self._annotate_tool = "highlight"
        self._thumb_loaded: set[int] = set()
        self._all_annotations: list[AnnotationItem] = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()
        self._prefs_timer = QTimer(self)
        self._prefs_timer.setSingleShot(True)
        self._prefs_timer.setInterval(400)
        self._prefs_timer.timeout.connect(self._save_reader_preferences)
        self._apply_reader_preferences()

    def _apply_reader_preferences(self) -> None:
        rs = settings_mgr.reader
        self._fit_mode = rs.fit_mode
        self._fixed_zoom = max(READER_ZOOM_MIN, min(READER_ZOOM_MAX, rs.fixed_zoom))
        self._layout_mode = rs.layout_mode
        self._update_fit_buttons()
        if hasattr(self, "_layout_seg"):
            self._layout_seg.blockSignals(True)
            self._layout_seg.setCurrentItem(rs.layout_mode)
            self._layout_seg.blockSignals(False)
        if hasattr(self, "_splitter"):
            total = sum(self._splitter.sizes()) or 1140
            sidebar = min(max(rs.sidebar_width, 160), 480)
            self._splitter.setSizes([sidebar, max(400, total - sidebar)])

    def _schedule_save_preferences(self) -> None:
        self._prefs_timer.start()

    def _save_reader_preferences(self) -> None:
        rs = settings_mgr.settings.reader
        rs.fit_mode = self._fit_mode
        rs.fixed_zoom = self._fixed_zoom
        rs.layout_mode = self._layout_mode
        if self._splitter.sizes():
            rs.sidebar_width = self._splitter.sizes()[0]
        settings_mgr.save()

    def _setup_ui(self) -> None:
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(16)

        self._title = TitleLabel("PDF 阅读与批注")
        root.addWidget(self._title)
        self._wps_hint = wps_hint_label("reader")
        root.addWidget(self._wps_hint)
        self._intro = CaptionLabel("连续阅读 · 按需渲染 · 书签/搜索 · 多种批注类型")
        root.addWidget(self._intro)

        self._toolbar_host = QWidget()
        toolbar_outer = QVBoxLayout(self._toolbar_host)
        toolbar_outer.setContentsMargins(0, 0, 0, 0)
        toolbar_outer.addLayout(self._build_toolbar())
        root.addWidget(self._toolbar_host)

        self._sidebar = self._build_sidebar()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._build_view_area())
        splitter.setSizes([240, 900])
        self._splitter = splitter
        splitter.splitterMoved.connect(self._on_splitter_moved)
        root.addWidget(splitter, 1)

        self._status = CaptionLabel("请打开 PDF 文件")
        self._status.setStyleSheet("color:#888;")
        root.addWidget(self._status)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        open_btn = PrimaryPushButton(FluentIcon.FOLDER, "打开 PDF")
        open_btn.clicked.connect(self._open_pdf)
        row.addWidget(open_btn)

        self._mode_seg = SegmentedWidget()
        self._mode_seg.addItem("read", "阅读")
        self._mode_seg.addItem("annotate", "批注")
        self._mode_seg.setCurrentItem("read")
        self._mode_seg.currentItemChanged.connect(self._on_mode_changed)
        row.addWidget(self._mode_seg)

        row.addWidget(CaptionLabel("批注工具："))
        self._tool_combo = StudioComboBox()
        for _key, label in self.TOOL_OPTIONS:
            self._tool_combo.addItem(label)
        self._tool_combo.currentIndexChanged.connect(self._on_tool_combo_changed)
        self._tool_combo.setVisible(False)
        row.addWidget(self._tool_combo)

        row.addWidget(CaptionLabel("图章："))
        self._stamp_combo = StudioComboBox()
        self._stamp_combo.addItems(list(STAMP_NAMES.keys()))
        self._stamp_combo.setVisible(False)
        row.addWidget(self._stamp_combo)

        row.addWidget(CaptionLabel("缩放："))
        self._zoom_combo = StudioComboBox()
        self._zoom_combo.addItems(list(self.ZOOM_PRESETS.keys()))
        self._zoom_combo.setCurrentIndex(2)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_combo_changed)
        row.addWidget(self._zoom_combo)

        self._fit_btn_group = QButtonGroup(self)
        self._fit_width_btn = PushButton("适应宽度")
        self._fit_width_btn.setCheckable(True)
        self._fit_width_btn.setChecked(True)
        self._fit_width_btn.clicked.connect(lambda: self._set_fit_mode("fit_width"))
        self._fit_height_btn = PushButton("适应页高")
        self._fit_height_btn.setCheckable(True)
        self._fit_height_btn.clicked.connect(lambda: self._set_fit_mode("fit_height"))
        self._fit_actual_btn = PushButton("100%")
        self._fit_actual_btn.setCheckable(True)
        self._fit_actual_btn.clicked.connect(lambda: self._set_fit_mode("actual"))
        for btn in (self._fit_width_btn, self._fit_height_btn, self._fit_actual_btn):
            self._fit_btn_group.addButton(btn)
            row.addWidget(btn)

        self._layout_seg = SegmentedWidget()
        self._layout_seg.addItem("single", "单页")
        self._layout_seg.addItem("dual", "双页")
        self._layout_seg.setCurrentItem("single")
        self._layout_seg.currentItemChanged.connect(self._on_layout_mode_changed)
        row.addWidget(self._layout_seg)

        row.addWidget(CaptionLabel("页码："))
        self._page_spin = SpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.valueChanged.connect(self._goto_page)
        row.addWidget(self._page_spin)

        row.addStretch()

        self._search_edit = LineEdit()
        self._search_edit.setPlaceholderText("全文搜索…")
        self._search_edit.setFixedWidth(180)
        self._search_edit.returnPressed.connect(self._run_search)
        row.addWidget(self._search_edit)

        search_btn = PushButton(FluentIcon.SEARCH, "搜索")
        search_btn.clicked.connect(self._run_search)
        row.addWidget(search_btn)

        prev_btn = ToolButton(FluentIcon.UP)
        prev_btn.clicked.connect(self._prev_hit)
        next_btn = ToolButton(FluentIcon.DOWN)
        next_btn.clicked.connect(self._next_hit)
        row.addWidget(prev_btn)
        row.addWidget(next_btn)

        save_btn = PushButton(FluentIcon.SAVE, "另存为…")
        save_btn.clicked.connect(lambda: self._save_annotations(in_place=False))
        row.addWidget(save_btn)

        save_inplace_btn = PushButton("保存到原文件")
        save_inplace_btn.clicked.connect(lambda: self._save_annotations(in_place=True))
        row.addWidget(save_inplace_btn)

        self._undo_btn = ToolButton(FluentIcon.CANCEL)
        self._undo_btn.setToolTip("撤销 (Ctrl+Z)")
        self._undo_btn.clicked.connect(self._undo)
        self._redo_btn = ToolButton(FluentIcon.SYNC)
        self._redo_btn.setToolTip("重做 (Ctrl+Y)")
        self._redo_btn.clicked.connect(self._redo)
        row.addWidget(self._undo_btn)
        row.addWidget(self._redo_btn)

        self._focus_btn = ToolButton(FluentIcon.VIEW)
        self._focus_btn.setToolTip("专注阅读（隐藏侧栏与工具栏）")
        self._focus_btn.clicked.connect(self._toggle_focus_mode)
        row.addWidget(self._focus_btn)

        self._fullscreen_btn = ToolButton(FluentIcon.FULL_SCREEN)
        self._fullscreen_btn.setToolTip("窗口全屏 (Esc 退出)")
        self._fullscreen_btn.clicked.connect(self._toggle_window_fullscreen)
        row.addWidget(self._fullscreen_btn)

        return row

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(200)
        panel.setMaximumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        self._sidebar_stack = QStackedWidget()
        thumb_page = QWidget()
        thumb_l = QVBoxLayout(thumb_page)
        thumb_l.setContentsMargins(0, 0, 0, 0)
        thumb_l.addWidget(StrongBodyLabel("缩略图"))
        self._thumb_list = QListWidget()
        apply_list_widget_style(self._thumb_list)
        self._thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        thumb_l.addWidget(self._thumb_list)

        bm_page = QWidget()
        bm_l = QVBoxLayout(bm_page)
        bm_l.setContentsMargins(0, 0, 0, 0)
        bm_l.addWidget(StrongBodyLabel("书签"))
        self._bookmark_tree = QTreeWidget()
        self._bookmark_tree.setHeaderHidden(True)
        self._bookmark_tree.itemClicked.connect(self._on_bookmark_clicked)
        bm_l.addWidget(self._bookmark_tree)

        ann_page = QWidget()
        ann_l = QVBoxLayout(ann_page)
        ann_l.setContentsMargins(0, 0, 0, 0)
        ann_l.addWidget(StrongBodyLabel("批注列表"))

        filter_row = QHBoxLayout()
        filter_row.addWidget(CaptionLabel("筛选："))
        self._annot_filter = StudioComboBox()
        self._annot_filter.addItems(self.ANNOT_FILTER_OPTIONS)
        self._annot_filter.currentIndexChanged.connect(self._refresh_annot_list)
        filter_row.addWidget(self._annot_filter, 1)
        ann_l.addLayout(filter_row)

        self._annot_list = QListWidget()
        apply_list_widget_style(self._annot_list)
        self._annot_list.itemDoubleClicked.connect(self._on_annot_item_activated)
        ann_l.addWidget(self._annot_list)

        ann_btn_row = QHBoxLayout()
        del_btn = PushButton("删除选中")
        del_btn.clicked.connect(self._delete_selected_annotation)
        export_btn = PushButton("导出摘要")
        export_btn.clicked.connect(self._export_annot_summary)
        ann_btn_row.addWidget(del_btn)
        ann_btn_row.addWidget(export_btn)
        ann_l.addLayout(ann_btn_row)

        self._sidebar_stack.addWidget(thumb_page)
        self._sidebar_stack.addWidget(bm_page)
        self._sidebar_stack.addWidget(ann_page)
        layout.addWidget(self._sidebar_stack)

        nav_row = QHBoxLayout()
        for i, label in enumerate(["缩略图", "书签", "批注"]):
            btn = PushButton(label)
            btn.clicked.connect(lambda _, idx=i: self._sidebar_stack.setCurrentIndex(idx))
            nav_row.addWidget(btn)
        layout.addLayout(nav_row)
        return panel

    def _build_view_area(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view_stack = QStackedWidget()

        self._drop_zone = DropZone("pdf", "拖放 PDF 到此处打开")
        self._drop_zone.filesDropped.connect(self._on_files_dropped)
        self._view_stack.addWidget(self._drop_zone)

        scroll_host = QWidget()
        self._scroll_host = scroll_host
        scroll_layout = QVBoxLayout(scroll_host)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setAcceptDrops(True)

        self._pages_host = QWidget()
        self._pages_host.setAcceptDrops(True)
        self._pages_layout = QVBoxLayout(self._pages_host)
        self._pages_layout.setContentsMargins(12, 12, 12, 12)
        self._pages_layout.setSpacing(8)
        self._pages_layout.addStretch()

        self._scroll.setWidget(self._pages_host)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self._scroll.viewport().installEventFilter(self)
        self._scroll.installEventFilter(self)
        self._pages_host.installEventFilter(self)
        scroll_host.installEventFilter(self)
        scroll_layout.addWidget(self._scroll)
        self._view_stack.addWidget(scroll_host)

        layout.addWidget(self._view_stack)

        self._focus_exit_btn = ToolButton(FluentIcon.CLOSE, scroll_host)
        self._focus_exit_btn.setToolTip("退出专注阅读 (Esc)")
        self._focus_exit_btn.clicked.connect(self._toggle_focus_mode)
        self._focus_exit_btn.hide()
        self._focus_exit_btn.raise_()

        self._apply_reader_theme()
        return panel

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_focus_exit_btn") and self._focus_exit_btn.isVisible():
            self._reposition_focus_exit_btn()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            win = self.window()
            if win.isFullScreen():
                win.showNormal()
                return
            if self._focus_mode:
                self._toggle_focus_mode()
                return
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            key = event.key()
            if key == Qt.Key.Key_Z and not (mods & Qt.KeyboardModifier.ShiftModifier):
                self._undo()
                return
            if key in (Qt.Key.Key_Y, Qt.Key.Key_Z) and (
                key == Qt.Key.Key_Y or mods & Qt.KeyboardModifier.ShiftModifier
            ):
                self._redo()
                return
        super().keyPressEvent(event)

    def _reposition_focus_exit_btn(self) -> None:
        btn = self._focus_exit_btn
        parent = btn.parentWidget()
        if parent:
            margin = 12
            btn.move(parent.width() - btn.width() - margin, margin)

    def eventFilter(self, obj, event) -> bool:
        scroll_host = getattr(self, "_scroll_host", None)
        if scroll_host is not None and obj is scroll_host and event.type() == QEvent.Type.Resize:
            if self._focus_mode:
                self._reposition_focus_exit_btn()

        scroll = getattr(self, "_scroll", None)
        pages_host = getattr(self, "_pages_host", None)
        if scroll is not None and pages_host is not None:
            scroll_targets = (scroll.viewport(), scroll, pages_host)
            if obj in scroll_targets:
                et = event.type()
                if et == QEvent.Type.Resize and obj is scroll.viewport():
                    if self._fit_mode in ("fit_width", "fit_height"):
                        QTimer.singleShot(0, self._apply_fit_mode)
                elif et == QEvent.Type.Wheel and obj is scroll.viewport():
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self._zoom_wheel(event.angleDelta().y())
                        return True
                elif et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                    if self._drag_accepts(event):
                        event.acceptProposedAction()
                        return True
                elif et == QEvent.Type.Drop:
                    if self._handle_file_drop(event):
                        return True
        return super().eventFilter(obj, event)

    def _drag_accepts(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if Path(url.toLocalFile()).suffix.lower() == ".pdf":
                return True
        return False

    def _handle_file_drop(self, event) -> bool:
        if not self._drag_accepts(event):
            return False
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if Path(u.toLocalFile()).suffix.lower() == ".pdf"
        ]
        if paths:
            self._try_load_pdf(paths[0])
            event.acceptProposedAction()
            return True
        return False

    def _on_files_dropped(self, paths: list) -> None:
        pdfs = [p for p in paths if Path(p).suffix.lower() == ".pdf"]
        if pdfs:
            self._try_load_pdf(pdfs[0])
        else:
            show_warning(self, "仅支持 PDF 文件")

    def _zoom_wheel(self, delta_y: int) -> None:
        if not self._page_views:
            return
        base = self._effective_zoom() if self._fit_mode != "fixed" else self._fixed_zoom
        factor = 1.0 + READER_ZOOM_WHEEL_STEP if delta_y > 0 else 1.0 - READER_ZOOM_WHEEL_STEP
        self._set_fixed_zoom(base * factor)

    def _toggle_focus_mode(self) -> None:
        self._focus_mode = not self._focus_mode
        self._title.setVisible(not self._focus_mode)
        self._wps_hint.setVisible(not self._focus_mode)
        self._intro.setVisible(not self._focus_mode)
        self._toolbar_host.setVisible(not self._focus_mode)
        self._status.setVisible(not self._focus_mode)
        self._sidebar.setVisible(not self._focus_mode)
        self._focus_exit_btn.setVisible(self._focus_mode)
        if self._focus_mode:
            self._reposition_focus_exit_btn()
            self.setFocus()
        tip = "退出专注阅读" if self._focus_mode else "专注阅读（隐藏侧栏与工具栏）"
        self._focus_btn.setToolTip(tip)
        if self._focus_mode and self._pdf_path:
            self._view_stack.setCurrentIndex(1)

    def _toggle_window_fullscreen(self) -> None:
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
            self._fullscreen_btn.setToolTip("窗口全屏 (Esc 退出)")
        else:
            win.showFullScreen()
            self._fullscreen_btn.setToolTip("退出全屏 (Esc)")

    def _on_splitter_moved(self, *_args) -> None:
        self._on_view_geometry_changed()
        self._schedule_save_preferences()

    def _on_layout_mode_changed(self, key: str) -> None:
        if key not in ("single", "dual") or key == self._layout_mode:
            return
        self._layout_mode = key
        if self._page_count > 0:
            center = self._center_page_index()
            self._build_page_views(self._page_count)
            self._refresh_overlays()
            QTimer.singleShot(0, lambda: (
                self._apply_fit_mode(),
                self._goto_page(center + 1),
            ))
        self._schedule_save_preferences()

    def _apply_reader_theme(self) -> None:
        dark = isDarkTheme()
        bg = "#1e1e1e" if dark else "#f0f0f0"
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
        self._pages_host.setStyleSheet(f"background: {bg};")
        apply_list_widget_style(self._thumb_list, dark=dark)
        apply_list_widget_style(self._annot_list, dark=dark)
        for view in self._page_views:
            view.apply_reader_theme(dark)

    def _show_reader_view(self) -> None:
        self._view_stack.setCurrentIndex(1)

    def _show_drop_view(self) -> None:
        self._view_stack.setCurrentIndex(0)

    def _on_view_geometry_changed(self, *_args) -> None:
        if self._fit_mode in ("fit_width", "fit_height"):
            QTimer.singleShot(0, self._apply_fit_mode)

    def _page_viewport_width(self) -> int:
        vw, _ = self._viewport_size()
        if self._layout_mode == "dual":
            return max(1, (vw - READER_DUAL_GAP) // 2)
        return vw

    def _layout_geometries(self):
        y = 0
        for block, pages in self._layout_blocks:
            h = block.height()
            yield y, y + h, pages
            y += h + READER_LAYOUT_SPACING

    def _block_for_page(self, page_index: int) -> QWidget | None:
        for block, pages in self._layout_blocks:
            if page_index in pages:
                return block
        return None

    def _on_scroll_changed(self, _value: int) -> None:
        self._update_visible_renders()
        self._sync_current_page_from_scroll()
        if self._fit_mode == "fit_height":
            self._maybe_refit_for_center_page()

    # ── 缩放 / 适应模式 ───────────────────────

    def _viewport_size(self) -> tuple[int, int]:
        vp = self._scroll.viewport()
        return max(1, vp.width()), max(1, vp.height())

    def _reference_page_size(self, page_index: int | None = None) -> tuple[float, float]:
        if page_index is not None and 0 <= page_index < len(self._page_sizes):
            return self._page_sizes[page_index]
        return self._max_page_width, self._max_page_height

    def _effective_zoom(self, page_index: int | None = None) -> float:
        vw = self._page_viewport_width()
        _, vh = self._viewport_size()
        if self._fit_mode == "fit_height":
            idx = page_index if page_index is not None else self._center_page_index()
            pw, ph = self._reference_page_size(idx)
        elif self._fit_mode == "fit_width":
            pw, ph = self._max_page_width, self._max_page_height
        else:
            pw, ph = self._reference_page_size(0)
        return compute_reader_zoom(
            vw,
            vh,
            pw,
            ph,
            self._fit_mode if self._fit_mode != "fixed" else "fixed",
            fixed_zoom=self._fixed_zoom,
        )

    def _set_fit_mode(self, mode: str) -> None:
        self._fit_mode = mode
        if mode == "fit_height":
            self._fit_height_anchor = self._center_page_index()
        self._update_fit_buttons()
        self._apply_fit_mode()
        self._schedule_save_preferences()

    def _update_fit_buttons(self) -> None:
        self._fit_width_btn.setChecked(self._fit_mode == "fit_width")
        self._fit_height_btn.setChecked(self._fit_mode == "fit_height")
        self._fit_actual_btn.setChecked(self._fit_mode == "actual")

    def _apply_fit_mode(self) -> None:
        if not self._page_views:
            return
        self._zoom = self._effective_zoom()
        self._update_zoom_status()
        self._invalidate_renders_for_zoom()

    def _set_fixed_zoom(self, zoom: float) -> None:
        zoom = max(READER_ZOOM_MIN, min(READER_ZOOM_MAX, zoom))
        self._fit_mode = "fixed"
        self._fixed_zoom = zoom
        self._zoom = zoom
        self._update_fit_buttons()
        matched = False
        for i, (label, val) in enumerate(self.ZOOM_PRESETS.items()):
            if abs(val - zoom) < 0.01:
                self._zoom_combo.blockSignals(True)
                self._zoom_combo.setCurrentIndex(i)
                self._zoom_combo.blockSignals(False)
                matched = True
                break
        if not matched:
            self._zoom_combo.blockSignals(True)
            self._zoom_combo.setCurrentIndex(-1)
            self._zoom_combo.blockSignals(False)
        self._update_zoom_status()
        self._invalidate_renders_for_zoom()
        self._schedule_save_preferences()

    def _on_zoom_combo_changed(self, index: int) -> None:
        label = self._zoom_combo.currentText()
        zoom = self.ZOOM_PRESETS.get(label, 1.0)
        self._set_fixed_zoom(zoom)

    def _update_zoom_status(self) -> None:
        if not self._pdf_path:
            return
        base = self._status.text().split("  ·  缩放")[0]
        pct = int(round(self._effective_zoom() * 100))
        mode_label = {
            "fit_width": "适应宽度",
            "fit_height": "适应页高",
            "actual": "100%",
            "fixed": "自定义",
        }.get(self._fit_mode, "")
        self._status.setText(f"{base}  ·  缩放 {pct}% ({mode_label})")

    def _maybe_refit_for_center_page(self) -> None:
        center = self._center_page_index()
        if center == self._fit_height_anchor:
            return
        self._fit_height_anchor = center
        new_zoom = self._effective_zoom(center)
        if abs(new_zoom - self._zoom) < 0.02:
            return
        self._zoom = new_zoom
        self._update_zoom_status()
        self._invalidate_renders_for_zoom()

    def _center_page_index(self) -> int:
        if not self._layout_blocks:
            return 0
        scroll_top = self._scroll.verticalScrollBar().value()
        viewport_h = self._scroll.viewport().height()
        center_y = scroll_top + viewport_h // 2
        for top, bottom, pages in self._layout_geometries():
            if top <= center_y <= bottom:
                if len(pages) == 1:
                    return pages[0]
                mid_y = (top + bottom) // 2
                return pages[1] if center_y >= mid_y else pages[0]
        first, last = self._visible_page_range()
        return first if first == last else (first + last) // 2

    def _sync_current_page_from_scroll(self) -> None:
        if not self._page_views or self._syncing_page_spin:
            return
        page_num = self._center_page_index() + 1
        if self._page_spin.value() != page_num:
            self._syncing_page_spin = True
            self._page_spin.blockSignals(True)
            self._page_spin.setValue(page_num)
            self._page_spin.blockSignals(False)
            self._syncing_page_spin = False
            row = page_num - 1
            if 0 <= row < self._thumb_list.count():
                self._thumb_list.blockSignals(True)
                self._thumb_list.setCurrentRow(row)
                self._thumb_list.blockSignals(False)

    # ── 批注编辑状态 ─────────────────────────

    def has_unsaved_changes(self) -> bool:
        return bool(self._pending) or bool(self._deleted_xrefs)

    def _confirm_discard(self, action: str) -> bool:
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self,
            "未保存的批注",
            f"当前有未保存的批注更改，确定放弃并{action}吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _edit_state(self) -> tuple[list[AnnotationItem], set[int]]:
        return copy.deepcopy(self._pending), set(self._deleted_xrefs)

    def _apply_edit_state(self, state: tuple[list[AnnotationItem], set[int]]) -> None:
        self._pending, self._deleted_xrefs = state
        self._refresh_annot_list()
        self._refresh_overlays()

    def _push_undo(self) -> None:
        self._undo_stack.append(self._edit_state())
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._edit_state())
        self._apply_edit_state(self._undo_stack.pop())

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._edit_state())
        self._apply_edit_state(self._redo_stack.pop())

    # ── 文件加载 ──────────────────────────────

    def _try_load_pdf(self, path: str) -> None:
        if (
            self._pdf_path
            and Path(path).resolve() == Path(self._pdf_path).resolve()
        ):
            return
        if not self._confirm_discard("打开新文档"):
            return
        self._load_pdf(path)

    def _open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF (*.pdf)")
        if not path:
            return
        self._try_load_pdf(path)

    def _load_pdf(self, path: str, password: str = "", *, skip_discard_confirm: bool = False) -> None:
        if not skip_discard_confirm and self._pdf_path:
            resolved = Path(path).resolve()
            if resolved != Path(self._pdf_path).resolve():
                if not self._confirm_discard("打开新文档"):
                    return
        try:
            info = PDFReaderUtil.get_info(path, password=password)
        except ValueError as e:
            msg = str(e)
            if "加密" in msg or "密码" in msg:
                pwd, ok = QInputDialog.getText(
                    self, "PDF 密码", "该 PDF 已加密，请输入密码：",
                    echo=QLineEdit.EchoMode.Password,
                )
                if ok and pwd:
                    self._load_pdf(path, pwd, skip_discard_confirm=True)
                return
            show_error(self, "无法打开", msg)
            return
        except Exception as e:
            show_error(self, "无法打开", str(e))
            return

        self._pdf_path = path
        self._password = password
        self._page_count = info.page_count
        self._pending.clear()
        self._deleted_xrefs.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._search_hits.clear()
        self._search_index = -1
        self._render_cache.clear()
        self._pending_renders.clear()
        self._thumb_loaded.clear()
        self._thumb_png_cache.clear()

        if info.pages:
            self._page_sizes = [(p.width, p.height) for p in info.pages]
            self._max_page_width = max((w for w, _ in self._page_sizes), default=595.0)
            self._max_page_height = max((h for _, h in self._page_sizes), default=842.0)
        else:
            self._page_sizes = []
            self._max_page_width = 595.0
            self._max_page_height = 842.0
        self._apply_reader_preferences()
        self._fit_height_anchor = 0

        self._page_spin.setRange(1, max(1, info.page_count))
        status_extra = ""
        if info.page_count > 200:
            status_extra = " · 大文档按需渲染"
            show_info(
                self,
                f"共 {info.page_count} 页，已启用按需渲染（滚动时加载可见页）",
            )

        self._status.setText(
            f"{Path(path).name}  ·  {info.page_count} 页  ·  "
            f"{get_file_size_str(path)}{status_extra}"
        )

        self._populate_bookmarks(info.bookmarks)
        self._populate_thumbnails(info.page_count)
        self._build_page_views(info.page_count)
        self._load_existing_annotations()
        self._show_reader_view()
        self._apply_reader_theme()
        QTimer.singleShot(0, self._apply_fit_mode)
        settings_mgr.add_recent_file(path)

    def open_document(self, path: str) -> None:
        """供首页等外部入口打开 PDF"""
        if Path(path).suffix.lower() != ".pdf":
            show_warning(self, "仅支持 PDF 文件")
            return
        self._try_load_pdf(path)

    def _populate_bookmarks(self, bookmarks: list[dict]) -> None:
        self._bookmark_tree.clear()
        if not bookmarks:
            item = QTreeWidgetItem(["（无书签）"])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._bookmark_tree.addTopLevelItem(item)
            return
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for bm in bookmarks:
            level = bm.get("level", 1)
            title = bm.get("title", "")
            page = bm.get("page", 0)
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self._bookmark_tree.addTopLevelItem(item)
            stack.append((level, item))

    def _populate_thumbnails(self, page_count: int) -> None:
        self._thumb_list.clear()
        for i in range(page_count):
            self._thumb_list.addItem(QListWidgetItem(f"第 {i + 1} 页"))
        self._load_thumb_batch(0)

    def _load_thumb_batch(self, start: int) -> None:
        if not self._pdf_path:
            return
        end = min(self._page_count, start + READER_THUMB_BATCH)
        indices = [i for i in range(start, end) if i not in self._thumb_loaded]
        if not indices:
            return
        for i in indices:
            self._thumb_loaded.add(i)
        w = ThumbnailWorker(
            self._pdf_path, indices, width=120, password=self._password,
        )
        w.signals.finished.connect(self._on_thumbnails_ready)
        submit_worker(w)

    def _on_thumbnails_ready(self, results: list[tuple[int, bytes]]) -> None:
        from PyQt6.QtGui import QIcon, QPixmap
        for page_idx, data in results:
            if page_idx >= self._thumb_list.count():
                continue
            self._thumb_png_cache[page_idx] = data
            pix = QPixmap()
            pix.loadFromData(data, "PNG")
            item = self._thumb_list.item(page_idx)
            if item:
                item.setIcon(QIcon(pix.scaled(100, 140, Qt.AspectRatioMode.KeepAspectRatio)))
            if (
                page_idx < len(self._page_views)
                and not self._render_cache.is_valid(page_idx, self._zoom)
            ):
                self._apply_thumb_placeholder(page_idx)

    def _apply_thumb_placeholder(self, page_index: int) -> None:
        data = self._thumb_png_cache.get(page_index)
        if not data or page_index >= len(self._page_views):
            return
        if page_index < len(self._page_sizes):
            pw, ph = self._page_sizes[page_index]
        else:
            pw, ph = self._max_page_width, self._max_page_height
        self._page_views[page_index].set_page_pixmap(data, pw, ph)

    def _create_page_view(self, page_index: int) -> PDFPageView:
        view = PDFPageView(page_index)
        view.apply_reader_theme(isDarkTheme())
        view.regionSelected.connect(self._on_region_selected)
        view.pageClicked.connect(self._on_page_clicked)
        view.inkDrawn.connect(self._on_ink_drawn)
        view.noteClicked.connect(self._on_note_clicked)
        view.freetextResized.connect(self._on_freetext_resized)
        view.clear_page_pixmap(READER_PLACEHOLDER_HEIGHT)
        return view

    def _build_page_views(self, page_count: int) -> None:
        while self._pages_layout.count() > 0:
            item = self._pages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._page_views.clear()
        self._layout_blocks.clear()

        views = [self._create_page_view(i) for i in range(page_count)]
        self._page_views = views

        if self._layout_mode == "dual":
            for i in range(0, page_count, 2):
                block = QWidget()
                row = QHBoxLayout(block)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(READER_DUAL_GAP)
                pages = [i]
                row.addWidget(views[i], 1)
                if i + 1 < page_count:
                    pages.append(i + 1)
                    row.addWidget(views[i + 1], 1)
                else:
                    spacer = QWidget()
                    spacer.setSizePolicy(
                        views[i].sizePolicy().horizontalPolicy(),
                        views[i].sizePolicy().verticalPolicy(),
                    )
                    row.addWidget(spacer, 1)
                label = BodyLabel(
                    f"— 第 {i + 1}–{pages[-1] + 1} 页 —"
                    if len(pages) > 1
                    else f"— 第 {i + 1} 页 —"
                )
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet("color:#999;")
                wrapper = QWidget()
                col = QVBoxLayout(wrapper)
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(4)
                col.addWidget(label)
                col.addWidget(block)
                self._pages_layout.addWidget(wrapper)
                self._layout_blocks.append((wrapper, pages))
        else:
            for i, view in enumerate(views):
                label = BodyLabel(f"— 第 {i + 1} 页 —")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet("color:#999;")
                block = QWidget()
                col = QVBoxLayout(block)
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(4)
                col.addWidget(label)
                col.addWidget(view)
                self._pages_layout.addWidget(block)
                self._layout_blocks.append((block, [i]))

        self._pages_layout.addStretch()
        self._apply_annotate_mode()
        self._refresh_overlays()

    def _visible_page_range(self) -> tuple[int, int]:
        if not self._layout_blocks:
            return 0, 0
        scroll_top = self._scroll.verticalScrollBar().value()
        viewport_h = self._scroll.viewport().height()
        scroll_bottom = scroll_top + viewport_h

        first, last = 0, 0
        found = False
        for top, bottom, pages in self._layout_geometries():
            if bottom >= scroll_top and top <= scroll_bottom:
                if not found:
                    first = min(pages)
                    found = True
                last = max(pages)
        if not found:
            return 0, min(len(self._page_views) - 1, 0)
        return first, last

    def _update_visible_renders(self) -> None:
        if not self._pdf_path or not self._page_views:
            return
        first, last = self._visible_page_range()
        start = max(0, first - READER_RENDER_BUFFER)
        end = min(len(self._page_views) - 1, last + READER_RENDER_BUFFER)
        for i in range(start, end + 1):
            self._ensure_page_rendered(i)
        for batch_start in range(
            max(0, first - READER_RENDER_BUFFER),
            min(self._page_count, last + READER_THUMB_BATCH),
            READER_THUMB_BATCH,
        ):
            batch_end = min(batch_start + READER_THUMB_BATCH, self._page_count)
            if any(j not in self._thumb_loaded for j in range(batch_start, batch_end)):
                self._load_thumb_batch(batch_start)
                break

    def _ensure_page_rendered(self, page_index: int) -> None:
        if not self._pdf_path or page_index >= len(self._page_views):
            return
        zoom = self._zoom
        if self._render_cache.is_valid(page_index, zoom):
            return
        if page_index in self._pending_renders:
            return
        self._apply_thumb_placeholder(page_index)
        self._pending_renders.add(page_index)
        view = self._page_views[page_index]
        w = PDFPageRenderWorker(self._pdf_path, page_index, zoom, self._password)

        def on_done(result, idx=page_index, page_view=view, render_zoom=zoom):
            self._pending_renders.discard(idx)
            if idx >= len(self._page_views) or abs(self._zoom - render_zoom) > 0.02:
                return
            png, pw, ph = result
            page_view.set_page_pixmap(png, pw, ph)
            evicted = self._render_cache.touch(idx, render_zoom)
            for ei in evicted:
                if 0 <= ei < len(self._page_views):
                    self._page_views[ei].clear_page_pixmap(READER_PLACEHOLDER_HEIGHT)
            self._refresh_overlays()

        def on_err(_m, idx=page_index):
            self._pending_renders.discard(idx)

        w.signals.finished.connect(on_done)
        w.signals.error.connect(on_err)
        submit_worker(w)

    def _invalidate_renders_for_zoom(self) -> None:
        """缩放变更：清空缓存，清除所有已渲染页，仅重渲可见范围。"""
        self._render_cache.clear()
        self._pending_renders.clear()
        for view in self._page_views:
            if view.has_pixmap():
                view.clear_page_pixmap(READER_PLACEHOLDER_HEIGHT)
        self._update_visible_renders()

    def _invalidate_all_renders(self) -> None:
        self._render_cache.clear()
        self._pending_renders.clear()
        for view in self._page_views:
            view.clear_page_pixmap(READER_PLACEHOLDER_HEIGHT)
        self._update_visible_renders()

    def _load_existing_annotations(self) -> None:
        if not self._pdf_path:
            return
        try:
            self._existing = PDFAnnotationService().list_annotations(
                self._pdf_path, self._password
            )
        except Exception:
            self._existing = []
        self._refresh_annot_list()

    # ── 交互 ──────────────────────────────────

    def _on_mode_changed(self, key: str) -> None:
        annotate = key == "annotate"
        self._tool_combo.setVisible(annotate)
        self._stamp_combo.setVisible(annotate and self._annotate_tool == "stamp")
        self._apply_annotate_mode()
        if annotate:
            self._sidebar_stack.setCurrentIndex(2)

    def _on_tool_combo_changed(self, index: int) -> None:
        if 0 <= index < len(self.TOOL_OPTIONS):
            self._annotate_tool = self.TOOL_OPTIONS[index][0]
        self._stamp_combo.setVisible(
            self._mode_seg.currentRouteKey() == "annotate"
            and self._annotate_tool == "stamp"
        )
        self._apply_annotate_mode()

    def _apply_annotate_mode(self) -> None:
        annotate = self._mode_seg.currentRouteKey() == "annotate"
        for view in self._page_views:
            view.set_annotate_mode(annotate, self._annotate_tool)

    def _goto_page(self, page_num: int) -> None:
        idx = page_num - 1
        if 0 <= idx < len(self._page_views):
            self._syncing_page_spin = True
            block = self._block_for_page(idx)
            if block is not None:
                self._scroll.ensureWidgetVisible(block, 0, 80)
            self._ensure_page_rendered(idx)
            self._syncing_page_spin = False

    def _on_thumb_selected(self, row: int) -> None:
        if row >= 0:
            self._syncing_page_spin = True
            self._page_spin.blockSignals(True)
            self._page_spin.setValue(row + 1)
            self._page_spin.blockSignals(False)
            self._goto_page(row + 1)
            self._syncing_page_spin = False

    def _on_bookmark_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self._syncing_page_spin = True
            self._page_spin.setValue(int(page) + 1)
            self._goto_page(int(page) + 1)
            self._syncing_page_spin = False

    def _run_search(self) -> None:
        if not self._pdf_path:
            show_warning(self, "请先打开 PDF")
            return
        query = self._search_edit.text().strip()
        if not query:
            return
        w = PDFSearchWorker(self._pdf_path, query, self._password)
        w.signals.finished.connect(self._on_search_done)
        w.signals.error.connect(lambda m: show_error(self, "搜索失败", m))
        submit_worker(w)

    def _on_search_done(self, hits: list[SearchHit]) -> None:
        self._search_hits = hits
        self._search_index = 0 if hits else -1
        self._status.setText(f"找到 {len(hits)} 处匹配")
        self._refresh_overlays()
        if hits:
            self._goto_page(hits[0].page_index + 1)

    def _prev_hit(self) -> None:
        if not self._search_hits:
            return
        self._search_index = (self._search_index - 1) % len(self._search_hits)
        hit = self._search_hits[self._search_index]
        self._goto_page(hit.page_index + 1)
        self._refresh_overlays()

    def _next_hit(self) -> None:
        if not self._search_hits:
            return
        self._search_index = (self._search_index + 1) % len(self._search_hits)
        hit = self._search_hits[self._search_index]
        self._goto_page(hit.page_index + 1)
        self._refresh_overlays()

    def _on_region_selected(
        self, page_index: int, x0: float, y0: float, x1: float, y1: float,
    ) -> None:
        kind = self._annotate_tool
        if kind not in PDFPageView.RECT_TOOLS:
            return
        rect = (x0, y0, x1, y1)
        if kind in PDFPageView.TEXT_SNAP_TOOLS and self._pdf_path:
            try:
                rect = PDFViewerService.snap_selection_to_words(
                    self._pdf_path, page_index, rect, self._password,
                )
            except Exception:
                pass
        self._push_undo()
        self._pending.append(AnnotationItem(
            page_index=page_index,
            kind=kind,
            rect=rect,
        ))
        self._refresh_annot_list()
        self._refresh_overlays()
        labels = {
            "highlight": "高亮", "underline": "下划线", "strikeout": "删除线",
            "rect": "矩形", "line": "线条",
        }
        show_info(self, f"已添加{labels.get(kind, kind)}批注")

    def _on_page_clicked(self, page_index: int, px: float, py: float) -> None:
        tool = self._annotate_tool
        self._push_undo()
        if tool == "freetext":
            text, ok = QInputDialog.getText(self, "文本批注", "请输入批注内容：")
            if not ok or not text.strip():
                self._undo()
                return
            w, h = 180.0, 48.0
            self._pending.append(AnnotationItem(
                page_index=page_index,
                kind="freetext",
                rect=(px, py, px + w, py + h),
                content=text.strip(),
            ))
        elif tool == "note":
            text, ok = QInputDialog.getText(self, "便签", "请输入便签内容：")
            if not ok or not text.strip():
                self._undo()
                return
            self._pending.append(AnnotationItem(
                page_index=page_index,
                kind="note",
                rect=(px, py, px + 18, py + 18),
                content=text.strip(),
            ))
        elif tool == "stamp":
            stamp = self._stamp_combo.currentText() or "Approved"
            size = 120.0
            self._pending.append(AnnotationItem(
                page_index=page_index,
                kind="stamp",
                rect=(px, py, px + size, py + size * 0.5),
                stamp_name=stamp,
            ))
        else:
            self._undo()
            return
        self._refresh_annot_list()
        self._refresh_overlays()

    def _on_note_clicked(self, page_index: int, content: str, pending_idx: int) -> None:
        if pending_idx >= 0:
            text, ok = QInputDialog.getText(
                self, "便签", "编辑便签内容：", text=content,
            )
            if ok and text.strip():
                self._push_undo()
                self._pending[pending_idx].content = text.strip()
                self._refresh_annot_list()
                self._refresh_overlays()
            return
        QMessageBox.information(
            self, f"第 {page_index + 1} 页便签", content or "（空便签）",
        )

    def _on_freetext_resized(
        self,
        page_index: int,
        pending_idx: int,
        x0: float, y0: float, x1: float, y1: float,
    ) -> None:
        if not (0 <= pending_idx < len(self._pending)):
            return
        ann = self._pending[pending_idx]
        if ann.page_index != page_index or ann.kind != "freetext":
            return
        self._push_undo()
        ann.rect = (x0, y0, x1, y1)
        self._refresh_overlays()

    def _on_ink_drawn(self, page_index: int, points: list) -> None:
        if len(points) < 2:
            return
        self._push_undo()
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        rect = (min(xs), min(ys), max(xs), max(ys))
        self._pending.append(AnnotationItem(
            page_index=page_index,
            kind="ink",
            rect=rect,
            points=[(float(x), float(y)) for x, y in points],
        ))
        self._refresh_annot_list()
        self._refresh_overlays()
        show_info(self, "已添加手绘批注")

    def _refresh_overlays(self) -> None:
        search_by_page: dict[int, list[tuple]] = {}
        if self._search_hits:
            for i, hit in enumerate(self._search_hits):
                kind = "search" if i == self._search_index else "search_dim"
                search_by_page.setdefault(hit.page_index, []).append(
                    (hit.rect, kind, {}),
                )

        for view in self._page_views:
            overlays = []
            paths = []
            for ann in self._existing:
                if ann.xref in self._deleted_xrefs:
                    continue
                if ann.page_index != view.page_index:
                    continue
                if ann.kind == "ink" and ann.points:
                    paths.append((ann.points, "ink"))
                else:
                    overlays.append((
                        ann.rect, ann.kind,
                        {"content": ann.content, "pending_idx": None, "xref": ann.xref},
                    ))
            for idx, ann in enumerate(self._pending):
                if ann.page_index != view.page_index:
                    continue
                if ann.kind == "ink" and ann.points:
                    paths.append((ann.points, "ink"))
                else:
                    overlays.append((
                        ann.rect, ann.kind,
                        {"content": ann.content, "pending_idx": idx, "xref": ann.xref},
                    ))
            for rect, kind, meta in search_by_page.get(view.page_index, []):
                overlays.append((rect, kind, meta))
            view.set_overlay_rects(overlays, paths)

    @staticmethod
    def _kind_label(kind: str) -> str:
        return {
            "highlight": "高亮",
            "underline": "下划线",
            "strikeout": "删除线",
            "freetext": "文本",
            "note": "便签",
            "stamp": "图章",
            "ink": "手绘",
            "rect": "矩形",
            "line": "线条",
        }.get(kind, kind)

    def _filter_matches(self, ann: AnnotationItem) -> bool:
        filt = self._annot_filter.currentText()
        if filt == "全部":
            return True
        label = self._kind_label(ann.kind)
        if filt == "文本":
            return ann.kind == "freetext"
        if filt == "形状":
            return ann.kind in ("rect", "line")
        return label == filt

    def _refresh_annot_list(self) -> None:
        self._annot_list.clear()
        self._all_annotations = []
        for ann in self._existing:
            if ann.xref in self._deleted_xrefs:
                continue
            if self._filter_matches(ann):
                self._all_annotations.append(("existing", ann))
        for ann in self._pending:
            if self._filter_matches(ann):
                self._all_annotations.append(("pending", ann))

        for source, ann in self._all_annotations:
            kind_label = self._kind_label(ann.kind)
            text = ann.content or ann.stamp_name or kind_label
            prefix = "[已有]" if source == "existing" else "[待保存]"
            self._annot_list.addItem(
                f"{prefix} 第{ann.page_index + 1}页 · {kind_label} · {text[:24]}"
            )

    def _on_annot_item_activated(self, item: QListWidgetItem) -> None:
        row = self._annot_list.row(item)
        if row < 0 or row >= len(self._all_annotations):
            return
        _, ann = self._all_annotations[row]
        self._page_spin.setValue(ann.page_index + 1)
        self._goto_page(ann.page_index + 1)

    def _delete_selected_annotation(self) -> None:
        row = self._annot_list.currentRow()
        if row < 0 or row >= len(self._all_annotations):
            show_warning(self, "请先选中一条批注")
            return
        source, ann = self._all_annotations[row]
        self._push_undo()
        if source == "pending":
            try:
                self._pending.remove(ann)
            except ValueError:
                self._undo()
                return
        elif ann.xref:
            self._deleted_xrefs.add(ann.xref)
        else:
            self._undo()
            show_warning(self, "无法删除该批注")
            return
        self._refresh_annot_list()
        self._refresh_overlays()
        show_info(self, "已删除批注")

    def _export_annot_summary(self) -> None:
        all_ann = [
            a for a in self._existing if a.xref not in self._deleted_xrefs
        ] + self._pending
        if not all_ann:
            show_warning(self, "当前没有批注可导出")
            return
        default = "annotations_summary.txt"
        if self._pdf_path:
            default = f"{Path(self._pdf_path).stem}_annotations.txt"
        out, _ = QFileDialog.getSaveFileName(
            self, "导出批注摘要", default, "文本 (*.txt)",
        )
        if not out:
            return
        path = PDFAnnotationService().export_summary(all_ann, out)
        finish_output_task(self, "批注摘要已导出", path)

    def _save_annotations(self, *, in_place: bool = False) -> None:
        if not self._pdf_path:
            show_warning(self, "请先打开 PDF")
            return
        if not self._pending and not self._deleted_xrefs:
            show_warning(self, "没有需要保存的批注更改")
            return
        if in_place:
            reply = QMessageBox.warning(
                self,
                "覆盖原文件",
                f"将把批注更改写入原文件：\n{Path(self._pdf_path).name}\n"
                "此操作会直接修改原 PDF，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            out = self._pdf_path
        else:
            default = str(Path(self._pdf_path).with_name(
                f"{Path(self._pdf_path).stem}_annotated.pdf"
            ))
            out, _ = QFileDialog.getSaveFileName(
                self, "另存批注 PDF", default, "PDF (*.pdf)",
            )
            if not out:
                return
        w = PDFSaveAnnotationsWorker(
            self._pdf_path,
            out,
            list(self._pending),
            self._password,
            delete_xrefs=list(self._deleted_xrefs),
        )
        w.signals.finished.connect(lambda p: (
            finish_output_task(self, "批注已保存", p),
            self._pending.clear(),
            self._deleted_xrefs.clear(),
            self._undo_stack.clear(),
            self._redo_stack.clear(),
            self._load_pdf(str(p), self._password, skip_discard_confirm=True),
        ))
        w.signals.error.connect(lambda m: show_error(self, "保存失败", m))
        submit_worker(w)
