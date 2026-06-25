"""
PDF Studio - OCR 识别中心页面
支持PDF/图片OCR，多语言，多格式导出
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QTextEdit, QSplitter,
    QScrollArea,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    CheckBox, SubtitleLabel,
    StrongBodyLabel, FluentIcon, SpinBox,
    ProgressBar, TextEdit, ToolButton,
)

from app.widgets.combo_box import StudioComboBox
from app.widgets.common import (
    DropZone, TaskProgressCard,
    show_success, show_error, show_warning, show_info,
    wps_hint_label, finish_output_task,
)
from app.workers.base_worker import OCRWorker, submit_worker
from app.config.settings import settings_mgr
from app.config.constants import OCR_LANGUAGE_MAP, OCR_OUTPUT_FORMATS
from app.utils.helpers import get_file_size_str, open_in_explorer
from app.utils.logger import logger
from core.ocr.engine import OCROptions, OCRManager


class OCRPage(QWidget):
    """OCR 识别中心页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ocrPage")
        self._current_file: Optional[str] = None
        self._is_pdf: bool = True
        self._ocr_results = None
        self._current_worker: Optional[OCRWorker] = None
        self._setup_ui()
        self._check_engine()
        self._apply_setting_defaults()

    def _apply_setting_defaults(self) -> None:
        pdf = settings_mgr.pdf
        ocr = settings_mgr.ocr
        self._dpi_spin.setValue(ocr.default_dpi or pdf.default_dpi)
        self._conf_spin.setValue(int(round(ocr.confidence_threshold * 100)))
        fmt_display = {
            "txt": "TXT",
            "docx": "DOCX",
            "markdown": "Markdown",
            "json": "JSON",
            "searchable_pdf": "可搜索PDF",
        }
        self._format_combo.setCurrentText(fmt_display.get(ocr.output_format, "TXT"))
        if pdf.default_output_dir:
            self._output_dir_edit.setText(pdf.default_output_dir)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("OCR 识别中心"))
        root.addWidget(wps_hint_label("ocr"))
        root.addWidget(CaptionLabel("本地离线识别 · 支持中/英/日/韩文 · 多格式导出"))

        # 引擎状态提示
        self._engine_status = CaptionLabel("")
        root.addWidget(self._engine_status)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左：控制面板
        splitter.addWidget(self._build_control_panel())
        # 右：结果预览
        splitter.addWidget(self._build_result_panel())
        splitter.setSizes([400, 560])

        root.addWidget(splitter, 1)

        self._progress_card = TaskProgressCard("准备就绪")
        self._progress_card.setVisible(False)
        self._progress_card.cancelRequested.connect(self._cancel)
        root.addWidget(self._progress_card)

    def _build_control_panel(self) -> QWidget:
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(460)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)
        scroll.setWidget(container)

        # 文件导入
        import_card = CardWidget()
        imp_layout = QVBoxLayout(import_card)
        imp_layout.setContentsMargins(16, 14, 16, 14)
        imp_layout.setSpacing(10)
        imp_layout.addWidget(StrongBodyLabel("导入文件"))

        self._drop_zone = DropZone(
            accept_types="all",
            hint_text="拖放PDF或图片文件到此处"
        )
        self._drop_zone.filesDropped.connect(self._on_file_dropped)
        imp_layout.addWidget(self._drop_zone)

        self._file_info = CaptionLabel("")
        self._file_info.setStyleSheet("color: #888;")
        imp_layout.addWidget(self._file_info)
        layout.addWidget(import_card)

        # 语言设置
        lang_card = CardWidget()
        lang_layout = QVBoxLayout(lang_card)
        lang_layout.setContentsMargins(16, 14, 16, 14)
        lang_layout.setSpacing(10)
        lang_layout.addWidget(StrongBodyLabel("识别语言"))

        self._lang_checks: dict[str, CheckBox] = {}
        for lang_name, lang_code in OCR_LANGUAGE_MAP.items():
            cb = CheckBox(lang_name)
            cb.setChecked(lang_code in ["ch", "en"])
            self._lang_checks[lang_code] = cb
            lang_layout.addWidget(cb)
        layout.addWidget(lang_card)

        # 识别设置
        settings_card = CardWidget()
        set_layout = QVBoxLayout(settings_card)
        set_layout.setContentsMargins(16, 14, 16, 14)
        set_layout.setSpacing(10)
        set_layout.addWidget(StrongBodyLabel("识别设置"))

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(CaptionLabel("渲染DPI："))
        self._dpi_spin = SpinBox()
        self._dpi_spin.setRange(72, 400)
        self._dpi_spin.setValue(200)
        dpi_row.addWidget(self._dpi_spin)
        dpi_row.addStretch()
        set_layout.addLayout(dpi_row)

        conf_row = QHBoxLayout()
        conf_row.addWidget(CaptionLabel("置信度阈值："))
        self._conf_spin = SpinBox()
        self._conf_spin.setRange(0, 100)
        self._conf_spin.setValue(50)
        self._conf_spin.setSuffix("%")
        conf_row.addWidget(self._conf_spin)
        conf_row.addStretch()
        set_layout.addLayout(conf_row)

        layout.addWidget(settings_card)

        # 输出设置
        output_card = CardWidget()
        out_layout = QVBoxLayout(output_card)
        out_layout.setContentsMargins(16, 14, 16, 14)
        out_layout.setSpacing(10)
        out_layout.addWidget(StrongBodyLabel("导出设置"))

        out_layout.addWidget(CaptionLabel("导出格式："))
        self._format_combo = StudioComboBox()
        self._format_combo.addItems(["TXT", "DOCX", "Markdown", "JSON", "可搜索PDF"])
        out_layout.addWidget(self._format_combo)

        dir_row = QHBoxLayout()
        from qfluentwidgets import LineEdit
        self._output_dir_edit = LineEdit()
        self._output_dir_edit.setPlaceholderText("默认与源文件同目录")
        browse_btn = PushButton("浏览")
        browse_btn.clicked.connect(self._browse_output)
        dir_row.addWidget(self._output_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        out_layout.addLayout(dir_row)
        layout.addWidget(output_card)

        # 执行按钮
        self._ocr_btn = PrimaryPushButton(FluentIcon.SEARCH, "开始识别")
        self._ocr_btn.setFixedHeight(40)
        self._ocr_btn.clicked.connect(self._start_ocr)
        layout.addWidget(self._ocr_btn)

        self._export_btn = PushButton(FluentIcon.SAVE, "导出结果")
        self._export_btn.setFixedHeight(36)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_results)
        layout.addWidget(self._export_btn)

        layout.addStretch()
        return scroll

    def _build_result_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.addWidget(StrongBodyLabel("识别结果"))
        self._result_stats = CaptionLabel("")
        self._result_stats.setStyleSheet("color: #888;")
        header_row.addStretch()
        header_row.addWidget(self._result_stats)
        copy_btn = ToolButton(FluentIcon.COPY)
        copy_btn.setToolTip("复制全部文本")
        copy_btn.clicked.connect(self._copy_result)
        header_row.addWidget(copy_btn)
        layout.addLayout(header_row)

        self._result_edit = TextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("识别结果将显示在此处...")
        layout.addWidget(self._result_edit, 1)

        return panel

    # ─────────────────────────────────────────
    # 引擎检查
    # ─────────────────────────────────────────

    def _check_engine(self):
        manager = OCRManager(engine_name=settings_mgr.ocr.engine)
        if manager.is_available:
            self._engine_status.setText("✓ OCR 引擎就绪")
            self._engine_status.setStyleSheet("color: #107C10;")
        else:
            self._engine_status.setText(
                "⚠ OCR 引擎未安装  请运行：pip install rapidocr-onnxruntime"
            )
            self._engine_status.setStyleSheet("color: #FF8C00;")
            self._ocr_btn.setEnabled(False)

    # ─────────────────────────────────────────
    # 文件操作
    # ─────────────────────────────────────────

    def _on_file_dropped(self, paths: list[str]):
        if paths:
            p = paths[0]
            self._current_file = p
            self._is_pdf = Path(p).suffix.lower() == ".pdf"
            self._file_info.setText(
                f"{Path(p).name}  ·  {get_file_size_str(p)}"
                + ("  ·  PDF" if self._is_pdf else "  ·  图片")
            )
            settings_mgr.add_recent_file(p)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._output_dir_edit.setText(d)

    # ─────────────────────────────────────────
    # OCR 执行
    # ─────────────────────────────────────────

    def _start_ocr(self):
        if not self._current_file:
            show_warning(self, "请先导入文件")
            return

        langs = [code for code, cb in self._lang_checks.items() if cb.isChecked()]
        if not langs:
            show_warning(self, "请至少选择一种识别语言")
            return

        options = OCROptions(
            languages=langs,
            dpi=self._dpi_spin.value(),
            confidence_threshold=self._conf_spin.value() / 100.0,
        )

        self._ocr_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._progress_card.set_status("识别中...", "#0078D4")
        self._result_edit.clear()

        worker = OCRWorker(self._current_file, options, is_pdf=self._is_pdf)
        self._current_worker = worker
        worker.signals.progress.connect(self._progress_card.update_progress)
        worker.signals.message.connect(self._progress_card.set_message)
        worker.signals.finished.connect(self._on_ocr_done)
        worker.signals.error.connect(self._on_ocr_error)
        submit_worker(worker)

    def _on_ocr_done(self, results: list):
        self._ocr_results = results
        self._ocr_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._progress_card.set_finished(True)

        # 显示结果
        all_text = []
        total_blocks = 0
        for r in results:
            all_text.append(f"=== 第 {r.page_index + 1} 页 ===")
            all_text.append(r.full_text)
            all_text.append("")
            total_blocks += len(r.blocks)

        self._result_edit.setPlainText("\n".join(all_text))
        self._result_stats.setText(
            f"共 {len(results)} 页  |  {total_blocks} 个文字块"
        )

        saved_path, save_err = self._save_ocr_results()
        if saved_path:
            show_success(
                self,
                "识别完成",
                f"{len(results)} 页，{total_blocks} 个文字块\n已保存至：{saved_path.name}",
            )
            open_in_explorer(saved_path)
        elif save_err:
            show_warning(
                self,
                "识别完成，但保存失败",
                f"{save_err}\n可点击「导出结果」手动保存。",
            )
        else:
            show_success(self, "识别完成", f"{len(results)} 页，{total_blocks} 个文字块")

    def _on_ocr_error(self, msg: str):
        self._ocr_btn.setEnabled(True)
        self._progress_card.set_finished(False, msg)
        show_error(self, "识别失败", msg)

    def _cancel(self):
        if self._current_worker:
            self._current_worker.request_cancel()
            self._ocr_btn.setEnabled(True)

    # ─────────────────────────────────────────
    # 结果导出
    # ─────────────────────────────────────────

    def _get_export_format(self) -> str:
        fmt_map = {
            "TXT": "txt",
            "DOCX": "docx",
            "Markdown": "markdown",
            "JSON": "json",
            "可搜索PDF": "searchable_pdf",
        }
        return fmt_map.get(self._format_combo.currentText(), "txt")

    def _get_export_base_path(self) -> Path:
        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            output_dir = str(settings_mgr.resolve_output_dir(self._current_file))
        return Path(output_dir) / f"{Path(self._current_file).stem}_ocr"

    def _save_ocr_results(self) -> tuple[Optional[Path], Optional[str]]:
        """
        按当前导出设置保存识别结果。

        Returns:
            (保存路径, 错误信息)；成功时错误信息为 None
        """
        if not self._ocr_results:
            return None, "无可保存的识别结果"
        if not self._current_file:
            return None, "未找到源文件"

        fmt = self._get_export_format()
        if fmt == "searchable_pdf" and not self._is_pdf:
            fmt = "txt"
            logger.info("图片文件不支持可搜索PDF，已降级为 TXT 导出")

        base_path = self._get_export_base_path()
        base_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            manager = OCRManager(engine_name=settings_mgr.ocr.engine)
            if fmt == "searchable_pdf":
                out = manager.generate_searchable_pdf(
                    self._current_file,
                    self._ocr_results,
                    base_path.with_suffix(".pdf"),
                )
            else:
                out = manager.export_results(self._ocr_results, base_path, fmt)
            logger.info(f"OCR 结果已保存: {out}")
            return out, None
        except Exception as e:
            logger.exception(f"OCR 结果保存失败: {e}")
            return None, str(e)

    def _export_results(self):
        if not self._ocr_results:
            show_warning(self, "无可导出的识别结果")
            return

        out, err = self._save_ocr_results()
        if out:
            show_success(self, "导出完成", str(out))
            open_in_explorer(out)
        else:
            show_error(self, "导出失败", err or "未知错误")

    def _copy_result(self):
        from PyQt6.QtWidgets import QApplication
        text = self._result_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            show_info(self, "已复制到剪贴板")
