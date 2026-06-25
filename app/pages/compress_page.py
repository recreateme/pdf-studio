"""
PDF Studio - 压缩页面
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CheckBox,
    SpinBox, StrongBodyLabel, FluentIcon, LineEdit,
)
from app.widgets.common import DropZone, TaskProgressCard, show_success, show_error, show_warning, wps_hint_label, finish_output_task
from app.widgets.combo_box import StudioComboBox
from app.workers.base_worker import PDFCompressWorker, submit_worker
from app.config.settings import settings_mgr
from app.utils.helpers import get_file_size_str, open_in_explorer
from core.pdf.processor import CompressOptions


class CompressPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("compressPage")
        self._pdf_path: Optional[str] = None
        self._setup_ui()
        self._apply_setting_defaults()

    def _apply_setting_defaults(self) -> None:
        mode_map = {"high_quality": 0, "balanced": 1, "max_compress": 2}
        self._mode_combo.setCurrentIndex(
            mode_map.get(settings_mgr.pdf.compression_level, 1)
        )
        self._quality.setValue(settings_mgr.pdf.jpeg_quality)

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)
        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("PDF 压缩"))
        root.addWidget(wps_hint_label("compress"))
        root.addWidget(CaptionLabel("降低PDF文件大小，支持高质量/均衡/极限/智能四种模式"))

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(20, 16, 20, 16)
        c_l.setSpacing(14)

        c_l.addWidget(StrongBodyLabel("导入PDF"))
        drop = DropZone("pdf", "拖放PDF文件到此处")
        drop.filesDropped.connect(self._on_dropped)
        c_l.addWidget(drop)

        self._file_label = CaptionLabel("")
        self._file_label.setStyleSheet("color:#888;")
        c_l.addWidget(self._file_label)

        self._size_hint = CaptionLabel("")
        self._size_hint.setStyleSheet("color:#666;")
        c_l.addWidget(self._size_hint)

        c_l.addWidget(StrongBodyLabel("压缩模式"))
        self._mode_combo = StudioComboBox()
        self._mode_combo.addItems([
            "高质量（轻度压缩）",
            "均衡模式（推荐）",
            "极限压缩（画质降低）",
            "智能压缩（保留文字层）",
        ])
        self._mode_combo.setCurrentIndex(1)
        c_l.addWidget(self._mode_combo)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(CaptionLabel("图像DPI："))
        self._dpi = SpinBox()
        self._dpi.setRange(72, 300)
        self._dpi.setValue(120)
        dpi_row.addWidget(self._dpi)
        dpi_row.addStretch()
        c_l.addLayout(dpi_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(CaptionLabel("JPEG质量："))
        self._quality = SpinBox()
        self._quality.setRange(10, 100)
        self._quality.setValue(72)
        quality_row.addWidget(self._quality)
        quality_row.addStretch()
        c_l.addLayout(quality_row)

        self._remove_meta = CheckBox("删除元数据（作者/标题等）")
        c_l.addWidget(self._remove_meta)

        c_l.addWidget(StrongBodyLabel("输出路径"))
        out_row = QHBoxLayout()
        self._out_edit = LineEdit()
        self._out_edit.setPlaceholderText("压缩后PDF保存路径")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._out_edit.setText(
            QFileDialog.getSaveFileName(self, "保存压缩PDF", "compressed.pdf", "PDF (*.pdf)")[0]
            or self._out_edit.text()
        ))
        out_row.addWidget(self._out_edit, 1)
        out_row.addWidget(browse)
        c_l.addLayout(out_row)

        root.addWidget(card)

        self._compress_btn = PrimaryPushButton(FluentIcon.ZIP_FOLDER, "开始压缩")
        self._compress_btn.setFixedHeight(40)
        self._compress_btn.clicked.connect(self._start)
        root.addWidget(self._compress_btn)

        self._progress = TaskProgressCard("准备就绪")
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        root.addStretch()

    def _on_dropped(self, paths):
        if paths:
            self._pdf_path = paths[0]
            self._file_label.setText(f"{Path(paths[0]).name}  ·  {get_file_size_str(paths[0])}")
            self._size_hint.setText("压缩完成后将显示体积对比与页处理统计")

    def _start(self):
        if not self._pdf_path:
            show_warning(self, "请先导入PDF")
            return
        out = self._out_edit.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        mode_map = {0: "high_quality", 1: "balanced", 2: "max_compress", 3: "smart"}
        options = CompressOptions(
            output_path=Path(out),
            mode=mode_map[self._mode_combo.currentIndex()],
            image_dpi=self._dpi.value(),
            jpeg_quality=self._quality.value(),
            remove_metadata=self._remove_meta.isChecked(),
        )
        self._compress_btn.setEnabled(False)
        self._progress.setVisible(True)
        w = PDFCompressWorker(self._pdf_path, options)
        w.signals.progress.connect(self._progress.update_progress)
        w.signals.finished.connect(lambda result: (
            self._compress_btn.setEnabled(True),
            self._progress.set_finished(
                True,
                self._format_compress_summary(result),
            ),
            self._size_hint.setText(self._format_compress_summary(result)),
            finish_output_task(self, "压缩完成", result.path),
        ))
        w.signals.error.connect(lambda msg: (
            self._compress_btn.setEnabled(True),
            self._progress.set_finished(False, msg),
            show_error(self, "压缩失败", msg),
        ))
        submit_worker(w)

    @staticmethod
    def _format_compress_summary(result) -> str:
        def _fmt_size(num_bytes: int) -> str:
            if num_bytes < 1024:
                return f"{num_bytes} B"
            if num_bytes < 1024 * 1024:
                return f"{num_bytes / 1024:.1f} KB"
            return f"{num_bytes / 1024 / 1024:.2f} MB"

        msg = (
            f"原 {_fmt_size(result.original_size)} → "
            f"压缩后 {_fmt_size(result.compressed_size)}  "
            f"（节省 {result.savings_ratio:.1f}%）"
        )
        if result.pages_preserved or result.pages_rasterized:
            msg += (
                f"  ·  保留文字层 {result.pages_preserved} 页，"
                f"栅格化 {result.pages_rasterized} 页"
            )
        return msg
