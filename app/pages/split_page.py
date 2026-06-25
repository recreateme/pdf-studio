"""
PDF Studio - PDF 拆分页面
支持按页面范围、页数、书签、文件大小拆分
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFileDialog, QLabel,
    QSizePolicy, QSplitter, QButtonGroup,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    LineEdit, SpinBox,
    RadioButton, CheckBox, SubtitleLabel,
    StrongBodyLabel, SegmentedWidget,
    FluentIcon, InfoBar, InfoBarPosition,
    ProgressBar, ToolButton, Slider,
    ExpandLayout,
)

from app.widgets.common import (
    DropZone, ThumbnailPanel, TaskProgressCard,
    show_success, show_error, show_warning, show_info,
    wps_hint_label, finish_output_task,
)
from app.workers.base_worker import (
    PDFSplitWorker, ThumbnailWorker,
    PDFSplitByCountWorker, PDFSplitBySizeWorker, PDFSplitByBookmarkWorker,
    PDFSplitByBlankWorker,
    submit_worker,
)
from app.config.settings import settings_mgr
from app.config.constants import get_default_dpi, get_thumbnail_width
from app.utils.helpers import get_file_size_str, open_in_explorer
from app.utils.logger import logger
from core.pdf.processor import PDFReader as PDFReaderUtil, SplitOptions


class SplitPage(ScrollArea):
    """PDF 拆分页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("splitPage")

        self._pdf_path: Optional[str] = None
        self._pdf_info = None
        self._current_worker: Optional[PDFSplitWorker] = None
        self._thumb_worker: Optional[ThumbnailWorker] = None

        self._setup_ui()
        self._apply_setting_defaults()

    def _apply_setting_defaults(self) -> None:
        if settings_mgr.pdf.default_output_dir:
            self._output_dir_edit.setText(settings_mgr.pdf.default_output_dir)

    # ─────────────────────────────────────────

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        # 标题
        root.addWidget(TitleLabel("PDF 拆分"))
        root.addWidget(wps_hint_label("split"))
        root.addWidget(CaptionLabel("支持按页面范围、页数、书签、文件大小、空白页等多种方式拆分"))

        # ── 主体：左右分栏 ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左栏：控制面板
        left_panel = self._build_left_panel()
        splitter.addWidget(left_panel)

        # 右栏：缩略图预览
        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([420, 580])
        root.addWidget(splitter, 1)

        # ── 底部进度区 ────────────────────────
        self._progress_card = TaskProgressCard("准备就绪")
        self._progress_card.setVisible(False)
        self._progress_card.cancelRequested.connect(self._cancel)
        root.addWidget(self._progress_card)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(380)
        panel.setMaximumWidth(480)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)

        # ── 文件导入区 ────────────────────────
        import_card = CardWidget()
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(16, 14, 16, 14)
        import_layout.setSpacing(10)

        import_layout.addWidget(StrongBodyLabel("导入 PDF"))

        self._drop_zone = DropZone(accept_types="pdf", hint_text="拖放PDF文件到此处，或点击选择")
        self._drop_zone.filesDropped.connect(self._on_files_dropped)
        import_layout.addWidget(self._drop_zone)

        self._file_info_label = CaptionLabel("")
        self._file_info_label.setStyleSheet("color: #888;")
        import_layout.addWidget(self._file_info_label)

        layout.addWidget(import_card)

        # ── 拆分模式 ──────────────────────────
        mode_card = CardWidget()
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 14, 16, 14)
        mode_layout.setSpacing(12)

        mode_layout.addWidget(StrongBodyLabel("拆分模式"))

        self._mode_seg = SegmentedWidget()
        self._mode_seg.addItem("ranges", "自定义范围")
        self._mode_seg.addItem("count",  "按页数")
        self._mode_seg.addItem("size",   "按大小")
        self._mode_seg.addItem("bookmark", "按书签")
        self._mode_seg.addItem("blank", "按空白页")
        self._mode_seg.setCurrentItem("ranges")
        self._mode_seg.currentItemChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self._mode_seg)

        # 自定义范围输入
        self._ranges_widget = QWidget()
        ranges_layout = QVBoxLayout(self._ranges_widget)
        ranges_layout.setContentsMargins(0, 0, 0, 0)
        ranges_layout.setSpacing(6)
        ranges_layout.addWidget(CaptionLabel("页面范围（如：1-3,5,7-9）"))
        self._range_edit = LineEdit()
        self._range_edit.setPlaceholderText("例：1-5,8,10-12")
        ranges_layout.addWidget(self._range_edit)
        ranges_layout.addWidget(CaptionLabel("留空则按选中的缩略图页面拆分"))
        mode_layout.addWidget(self._ranges_widget)

        # 按页数
        self._count_widget = QWidget()
        count_layout = QHBoxLayout(self._count_widget)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.addWidget(CaptionLabel("每份页数："))
        self._pages_per_file = SpinBox()
        self._pages_per_file.setRange(1, 9999)
        self._pages_per_file.setValue(1)
        count_layout.addWidget(self._pages_per_file)
        count_layout.addStretch()
        self._count_widget.setVisible(False)
        mode_layout.addWidget(self._count_widget)

        # 按大小
        self._size_widget = QWidget()
        size_layout = QHBoxLayout(self._size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.addWidget(CaptionLabel("每份大小（MB）："))
        self._max_size = SpinBox()
        self._max_size.setRange(1, 2048)
        self._max_size.setValue(10)
        size_layout.addWidget(self._max_size)
        size_layout.addStretch()
        self._size_widget.setVisible(False)
        mode_layout.addWidget(self._size_widget)

        self._size_hint = CaptionLabel(
            "按平均每页体积估算拆分，实际输出大小可能略有偏差"
        )
        self._size_hint.setStyleSheet("color:#888;")
        self._size_hint.setVisible(False)
        mode_layout.addWidget(self._size_hint)

        # 按书签
        self._bookmark_widget = QWidget()
        bm_layout = QHBoxLayout(self._bookmark_widget)
        bm_layout.setContentsMargins(0, 0, 0, 0)
        bm_layout.addWidget(CaptionLabel("书签层级："))
        self._bookmark_level = SpinBox()
        self._bookmark_level.setRange(1, 6)
        self._bookmark_level.setValue(1)
        bm_layout.addWidget(self._bookmark_level)
        bm_layout.addStretch()
        self._bookmark_widget.setVisible(False)
        mode_layout.addWidget(self._bookmark_widget)

        # 按空白页
        self._blank_widget = QWidget()
        blank_layout = QVBoxLayout(self._blank_widget)
        blank_layout.setContentsMargins(0, 0, 0, 0)
        blank_layout.addWidget(CaptionLabel(
            "空白页（无文字、无图片、无矢量）作为章节分隔符，不会输出到结果中"
        ))
        self._blank_widget.setVisible(False)
        mode_layout.addWidget(self._blank_widget)

        layout.addWidget(mode_card)

        # ── 输出设置 ──────────────────────────
        output_card = CardWidget()
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(16, 14, 16, 14)
        output_layout.setSpacing(10)

        output_layout.addWidget(StrongBodyLabel("输出设置"))

        # 输出目录
        dir_row = QHBoxLayout()
        self._output_dir_edit = LineEdit()
        self._output_dir_edit.setPlaceholderText("默认：与源文件同目录")
        dir_row.addWidget(self._output_dir_edit, 1)
        browse_btn = PushButton("浏览")
        browse_btn.clicked.connect(self._browse_output_dir)
        dir_row.addWidget(browse_btn)
        output_layout.addWidget(CaptionLabel("输出目录"))
        output_layout.addLayout(dir_row)

        # 文件名模板
        output_layout.addWidget(CaptionLabel("文件名模板  {stem}=原文件名  {index}=序号"))
        self._name_template = LineEdit()
        self._name_template.setText("{stem}_part{index:03d}")
        output_layout.addWidget(self._name_template)

        # 覆盖选项
        self._overwrite_cb = CheckBox("覆盖同名文件")
        output_layout.addWidget(self._overwrite_cb)

        layout.addWidget(output_card)

        # ── 执行按钮 ──────────────────────────
        btn_row = QHBoxLayout()
        self._split_btn = PrimaryPushButton(FluentIcon.CUT, "开始拆分")
        self._split_btn.setFixedHeight(40)
        self._split_btn.clicked.connect(self._start_split)
        btn_row.addWidget(self._split_btn, 1)
        layout.addLayout(btn_row)

        layout.addStretch()
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 工具栏
        toolbar = QHBoxLayout()
        self._page_count_label = CaptionLabel("未加载文件")
        self._select_all_btn = PushButton("全选")
        self._select_all_btn.clicked.connect(lambda: self._thumb_panel.select_all())
        self._deselect_btn = PushButton("取消选择")
        self._deselect_btn.clicked.connect(lambda: self._thumb_panel.deselect_all())
        toolbar.addWidget(self._page_count_label)
        toolbar.addStretch()
        toolbar.addWidget(self._select_all_btn)
        toolbar.addWidget(self._deselect_btn)
        layout.addLayout(toolbar)

        # 缩略图面板
        self._thumb_panel = ThumbnailPanel()
        self._thumb_panel.selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._thumb_panel, 1)

        return panel

    # ─────────────────────────────────────────
    # 事件处理
    # ─────────────────────────────────────────

    def _on_files_dropped(self, paths: list[str]) -> None:
        if paths:
            self._load_pdf(paths[0])

    def _on_mode_changed(self, mode: str) -> None:
        self._ranges_widget.setVisible(mode == "ranges")
        self._count_widget.setVisible(mode == "count")
        self._size_widget.setVisible(mode == "size")
        self._size_hint.setVisible(mode == "size")
        self._bookmark_widget.setVisible(mode == "bookmark")
        self._blank_widget.setVisible(mode == "blank")

    def _on_selection_changed(self, selected: list[int]) -> None:
        count = len(selected)
        self._page_count_label.setText(
            f"共 {self._pdf_info.page_count if self._pdf_info else 0} 页  |  已选 {count} 页"
        )

    def _browse_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._output_dir_edit.setText(d)

    # ─────────────────────────────────────────
    # PDF 加载
    # ─────────────────────────────────────────

    def _load_pdf(self, path: str) -> None:
        try:
            self._pdf_info = PDFReaderUtil.get_info(path)
        except Exception as e:
            show_error(self, "文件错误", str(e))
            return

        self._pdf_path = path
        p = Path(path)
        self._file_info_label.setText(
            f"{p.name}  ·  {self._pdf_info.page_count} 页  ·  {get_file_size_str(path)}"
        )
        settings_mgr.add_recent_file(path)
        logger.info(f"加载PDF: {path}")
        self._load_thumbnails()

    def _load_thumbnails(self) -> None:
        if not self._pdf_path:
            return

        self._thumb_panel.clear()
        n = self._pdf_info.page_count
        self._page_count_label.setText(f"共 {n} 页  |  已选 0 页")

        # 先添加所有占位卡片
        for i in range(n):
            self._thumb_panel.add_page(i)

        # 后台批量渲染
        if self._thumb_worker:
            self._thumb_worker.request_cancel()

        self._thumb_worker = ThumbnailWorker(
            self._pdf_path, list(range(n)), width=get_thumbnail_width()
        )
        self._thumb_worker.signals.finished.connect(self._on_thumbnails_loaded)
        submit_worker(self._thumb_worker)

    def _on_thumbnails_loaded(self, results: list) -> None:
        for page_idx, png_bytes in results:
            card = self._thumb_panel.get_card(page_idx)
            if card:
                card.set_thumbnail(png_bytes)

    # ─────────────────────────────────────────
    # 拆分逻辑
    # ─────────────────────────────────────────

    def _start_split(self) -> None:
        if not self._pdf_path:
            show_warning(self, "请先导入PDF文件")
            return

        mode = self._mode_seg.currentRouteKey() or "ranges"
        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            output_dir = str(settings_mgr.task_output_dir(self._pdf_path, "_拆分"))

        options = SplitOptions(
            output_dir=Path(output_dir),
            name_template=self._name_template.text() or "{stem}_part{index:03d}",
            overwrite=self._overwrite_cb.isChecked(),
        )

        self._split_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._progress_card.set_status("处理中...", "#0078D4")

        if mode == "ranges":
            ranges = self._parse_ranges()
            if ranges is None:
                self._split_btn.setEnabled(True)
                return
            worker = PDFSplitWorker(self._pdf_path, ranges, options)
        elif mode == "count":
            worker = PDFSplitByCountWorker(
                self._pdf_path, self._pages_per_file.value(), options
            )
        elif mode == "size":
            worker = PDFSplitBySizeWorker(
                self._pdf_path, self._max_size.value(), options
            )
        elif mode == "bookmark":
            worker = PDFSplitByBookmarkWorker(
                self._pdf_path, self._bookmark_level.value(), options
            )
        elif mode == "blank":
            worker = PDFSplitByBlankWorker(self._pdf_path, options)
        else:
            self._split_btn.setEnabled(True)
            show_error(self, "模式错误", f"未知的拆分模式: {mode}")
            return

        self._current_worker = worker
        worker.signals.progress.connect(self._progress_card.update_progress)
        worker.signals.message.connect(self._progress_card.set_message)
        worker.signals.finished.connect(self._on_split_done)
        worker.signals.error.connect(self._on_split_error)
        worker.signals.cancelled.connect(lambda: self._progress_card.set_cancelled())
        submit_worker(worker)

    def _parse_ranges(self) -> Optional[list[tuple[int, int]]]:
        """
        解析范围字符串，同时考虑缩略图选中页
        格式：1-3,5,7-9 -> [(0,2),(4,4),(6,8)]
        """
        # 先看文本输入
        text = self._range_edit.text().strip()
        if text:
            ranges = []
            page_count = self._pdf_info.page_count if self._pdf_info else 0
            try:
                for part in text.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if "-" in part:
                        a, b = part.split("-", 1)
                        start = int(a) - 1
                        end = int(b) - 1
                    else:
                        n = int(part) - 1
                        start, end = n, n

                    if start < 0 or end < 0:
                        raise ValueError("页码必须从 1 开始")
                    if start > end:
                        raise ValueError("范围起始页不能大于结束页")
                    if page_count and end >= page_count:
                        raise ValueError(
                            f"页码超出范围（当前共 {page_count} 页）"
                        )
                    ranges.append((start, end))

                if not ranges:
                    show_warning(self, "未指定范围", "请输入有效的页面范围")
                    return None
                return ranges
            except ValueError:
                show_error(self, "格式错误", "页面范围格式有误，请检查输入")
                return None

        # 若无文本，用选中的缩略图
        selected = self._thumb_panel.get_selected()
        if not selected:
            show_warning(self, "未指定范围", "请输入页面范围或在缩略图中选择页面")
            return None

        # 将离散页码合并为连续范围
        ranges = []
        selected = sorted(selected)
        start = selected[0]
        prev = selected[0]
        for pg in selected[1:]:
            if pg == prev + 1:
                prev = pg
            else:
                ranges.append((start, prev))
                start = pg
                prev = pg
        ranges.append((start, prev))
        return ranges

    def _on_split_done(self, output_paths: list) -> None:
        self._split_btn.setEnabled(True)
        self._progress_card.set_finished(True, f"已生成 {len(output_paths)} 个文件")
        if output_paths:
            finish_output_task(self, "拆分完成", output_paths[0])

    def _on_split_error(self, msg: str) -> None:
        self._split_btn.setEnabled(True)
        self._progress_card.set_finished(False, msg)
        show_error(self, "拆分失败", msg)

    def _cancel(self) -> None:
        if self._current_worker:
            self._current_worker.request_cancel()
            self._split_btn.setEnabled(True)
