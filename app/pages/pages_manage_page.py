"""
PDF Studio - 页面管理
支持提取、删除、旋转 PDF 页面
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSplitter,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, StrongBodyLabel, FluentIcon,
    LineEdit, SegmentedWidget, BodyLabel, SpinBox,
)

from app.config.constants import get_thumbnail_width
from app.config.settings import settings_mgr
from app.utils.helpers import get_file_size_str, open_in_explorer
from app.widgets.common import (
    DropZone, ThumbnailPanel, TaskProgressCard,
    show_success, show_error, show_warning, finish_output_task, wps_hint_label,
)
from app.workers.base_worker import ThumbnailWorker, PDFPageManageWorker, submit_worker
from core.pdf.processor import PDFReader as PDFReaderUtil


class PagesManagePage(ScrollArea):
    """PDF 页面管理"""

    ACTION_MAP = {
        "extract": "extract",
        "delete": "delete",
        "rotate": "rotate",
        "insert_blank": "insert_blank",
        "duplicate": "duplicate",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pagesManagePage")
        self._pdf_path: Optional[str] = None
        self._page_count = 0
        self._thumb_worker: Optional[ThumbnailWorker] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("页面管理"))
        root.addWidget(wps_hint_label("pages"))
        root.addWidget(CaptionLabel("提取、删除、旋转、插入空白页或复制 PDF 页面"))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([400, 600])
        root.addWidget(splitter, 1)

        self._progress = TaskProgressCard("准备就绪")
        self._progress.setVisible(False)
        root.addWidget(self._progress)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)

        import_card = CardWidget()
        import_l = QVBoxLayout(import_card)
        import_l.setContentsMargins(16, 14, 16, 14)
        import_l.setSpacing(10)
        import_l.addWidget(StrongBodyLabel("导入 PDF"))

        drop = DropZone("pdf", "拖放 PDF 文件到此处")
        drop.filesDropped.connect(self._on_files_dropped)
        import_l.addWidget(drop)

        self._file_info = CaptionLabel("")
        self._file_info.setStyleSheet("color:#888;")
        import_l.addWidget(self._file_info)
        layout.addWidget(import_card)

        action_card = CardWidget()
        action_l = QVBoxLayout(action_card)
        action_l.setContentsMargins(16, 14, 16, 14)
        action_l.setSpacing(12)
        action_l.addWidget(StrongBodyLabel("操作类型"))

        self._action_seg = SegmentedWidget()
        self._action_seg.addItem("extract", "提取页面")
        self._action_seg.addItem("delete", "删除页面")
        self._action_seg.addItem("rotate", "旋转页面")
        self._action_seg.addItem("insert_blank", "插入空白")
        self._action_seg.addItem("duplicate", "复制页面")
        self._action_seg.setCurrentItem("extract")
        self._action_seg.currentItemChanged.connect(self._on_action_changed)
        action_l.addWidget(self._action_seg)

        action_l.addWidget(CaptionLabel("旋转角度（仅旋转模式）："))
        self._rotate_row = QWidget()
        rot_row = QHBoxLayout(self._rotate_row)
        rot_row.setContentsMargins(0, 0, 0, 0)
        self._rotate_seg = SegmentedWidget()
        self._rotate_seg.addItem("90", "90°")
        self._rotate_seg.addItem("180", "180°")
        self._rotate_seg.addItem("270", "270°")
        self._rotate_seg.setCurrentItem("90")
        rot_row.addWidget(self._rotate_seg)
        rot_row.addStretch()
        action_l.addWidget(self._rotate_row)

        self._blank_row = QWidget()
        blank_row = QHBoxLayout(self._blank_row)
        blank_row.setContentsMargins(0, 0, 0, 0)
        blank_row.addWidget(CaptionLabel("插入位置（页码，0=文档开头）："))
        self._after_page = SpinBox()
        self._after_page.setRange(0, 9999)
        self._after_page.setValue(0)
        blank_row.addWidget(self._after_page)
        blank_row.addWidget(CaptionLabel("数量："))
        self._blank_count = SpinBox()
        self._blank_count.setRange(1, 99)
        self._blank_count.setValue(1)
        blank_row.addWidget(self._blank_count)
        blank_row.addStretch()
        self._blank_row.setVisible(False)
        action_l.addWidget(self._blank_row)

        action_l.addWidget(CaptionLabel("页码范围（提取/删除/旋转/复制时使用，留空则用右侧选中页）"))
        self._range_edit = LineEdit()
        self._range_edit.setPlaceholderText("页码范围，例：1-3,5,7-9")
        action_l.addWidget(self._range_edit)

        out_row = QHBoxLayout()
        self._out_edit = LineEdit()
        self._out_edit.setPlaceholderText("输出 PDF 路径")
        browse = PushButton("浏览")
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit, 1)
        out_row.addWidget(browse)
        action_l.addLayout(out_row)
        layout.addWidget(action_card)

        hint = BodyLabel(
            "提取：将选中页保存为新 PDF\n"
            "删除：从文档中移除选中页\n"
            "旋转：顺时针旋转选中页\n"
            "插入空白：在指定页之后插入空白页\n"
            "复制：复制选中页并紧挨插入其后\n"
            "快捷：右侧可一键选中奇数页/偶数页（扫描件常用）"
        )
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        self._run_btn = PrimaryPushButton(FluentIcon.EDIT, "执行操作")
        self._run_btn.setFixedHeight(40)
        self._run_btn.clicked.connect(self._run)
        layout.addWidget(self._run_btn)
        layout.addStretch()
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._thumb_panel = ThumbnailPanel()

        toolbar = QHBoxLayout()
        toolbar.addWidget(StrongBodyLabel("页面预览"))
        toolbar.addStretch()
        sel_all = PushButton("全选")
        sel_all.clicked.connect(self._thumb_panel.select_all)
        desel = PushButton("取消选择")
        desel.clicked.connect(self._thumb_panel.deselect_all)
        toolbar.addWidget(sel_all)
        toolbar.addWidget(desel)
        odd_btn = PushButton("奇数页")
        odd_btn.clicked.connect(self._thumb_panel.select_odd_pages)
        even_btn = PushButton("偶数页")
        even_btn.clicked.connect(self._thumb_panel.select_even_pages)
        toolbar.addWidget(odd_btn)
        toolbar.addWidget(even_btn)
        layout.addLayout(toolbar)

        layout.addWidget(self._thumb_panel, 1)
        return panel

    def _on_action_changed(self, action: str) -> None:
        self._rotate_row.setVisible(action == "rotate")
        self._blank_row.setVisible(action == "insert_blank")
        self._range_edit.setEnabled(action != "insert_blank")

    def _browse_output(self) -> None:
        action = self._action_seg.currentRouteKey() or "extract"
        default = "pages_output.pdf"
        if action == "extract":
            default = "extracted.pdf"
        elif action == "delete":
            default = "deleted.pdf"
        elif action == "rotate":
            default = "rotated.pdf"
        elif action == "insert_blank":
            default = "with_blank.pdf"
        elif action == "duplicate":
            default = "duplicated.pdf"
        path = QFileDialog.getSaveFileName(self, "保存 PDF", default, "PDF (*.pdf)")[0]
        if path:
            self._out_edit.setText(path)

    def _on_files_dropped(self, paths: list[str]) -> None:
        if not paths:
            return
        self._load_pdf(paths[0])

    def _load_pdf(self, path: str) -> None:
        try:
            info = PDFReaderUtil.get_info(path)
        except Exception as e:
            show_error(self, "无法打开 PDF", str(e))
            return

        self._pdf_path = path
        self._page_count = info.page_count
        self._file_info.setText(
            f"{Path(path).name}  ·  {info.page_count} 页  ·  {get_file_size_str(path)}"
        )

        if settings_mgr.pdf.default_output_dir:
            out_dir = Path(settings_mgr.pdf.default_output_dir)
        else:
            out_dir = Path(path).parent
        self._out_edit.setText(str(out_dir / f"{Path(path).stem}_edited.pdf"))

        self._thumb_panel.clear()
        for i in range(info.page_count):
            self._thumb_panel.add_page(i)
        self._load_thumbnails()

    def _load_thumbnails(self) -> None:
        if not self._pdf_path:
            return
        indices = list(range(self._page_count))
        self._thumb_worker = ThumbnailWorker(
            self._pdf_path, indices, width=get_thumbnail_width()
        )

        def on_done(results: list[tuple[int, bytes]]) -> None:
            for page_idx, data in results:
                card = self._thumb_panel.get_card(page_idx)
                if card:
                    card.set_thumbnail(data)

        self._thumb_worker.signals.finished.connect(on_done)
        submit_worker(self._thumb_worker)

    def _resolve_page_indices(self) -> list[int]:
        spec = self._range_edit.text().strip()
        if spec:
            indices = PDFReaderUtil.parse_page_range(spec, self._page_count)
            if not indices:
                raise ValueError("页码范围无效或超出文档页数")
            return indices
        selected = self._thumb_panel.get_selected()
        if not selected:
            raise ValueError("请在缩略图中选择页面，或输入页码范围")
        return selected

    def _run(self) -> None:
        if not self._pdf_path:
            show_warning(self, "请先导入 PDF")
            return
        out = self._out_edit.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        action = self.ACTION_MAP.get(self._action_seg.currentRouteKey() or "extract", "extract")
        rotate_angle = int(self._rotate_seg.currentRouteKey() or "90")

        if action == "insert_blank":
            indices = []
        else:
            try:
                indices = self._resolve_page_indices()
            except ValueError as e:
                show_warning(self, str(e))
                return

        if action == "delete" and len(indices) >= self._page_count:
            show_warning(self, "不能删除全部页面，至少保留一页")
            return

        after_page = self._after_page.value() - 1 if self._after_page.value() > 0 else -1
        blank_count = self._blank_count.value()

        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        worker = PDFPageManageWorker(
            self._pdf_path, out, action, indices, rotate_angle,
            blank_count=blank_count,
            after_page_index=after_page,
        )
        worker.signals.progress.connect(self._progress.update_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        submit_worker(worker)

    def _on_finished(self, result_path) -> None:
        self._run_btn.setEnabled(True)
        self._progress.set_finished(True)
        finish_output_task(self, "操作完成", result_path)

    def _on_error(self, msg: str) -> None:
        self._run_btn.setEnabled(True)
        self._progress.set_finished(False, msg)
        show_error(self, "操作失败", msg)
