"""
PDF Studio - 批处理工作流中心
支持多步骤工作流：导入→OCR→压缩→水印→输出
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QListWidget, QListWidgetItem, QLabel, QTabWidget,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CheckBox,
    SpinBox, StrongBodyLabel, FluentIcon, LineEdit,
    SubtitleLabel, BodyLabel, TextEdit,
)
from app.widgets.combo_box import StudioComboBox
from app.widgets.list_styles import apply_list_widget_style
from app.widgets.common import (
    DropZone, TaskProgressCard, show_success, show_error,
    show_warning, show_info, wps_hint_label, finish_output_task,
)
from app.workers.base_worker import BaseWorker, submit_worker
from app.utils.helpers import collect_files, open_in_explorer
from app.utils.logger import logger
from app.utils.retry import run_with_retry
from app.utils.workflow_history import WorkflowHistoryStore
from app.config.settings import settings_mgr


def _workflow_max_attempts() -> int:
    wf = settings_mgr.workflow
    if not wf.auto_retry_on_failure:
        return 1
    return max(1, wf.retry_count)


class BatchWorkflowWorker(BaseWorker):
    """
    批处理工作流 Worker
    按顺序执行：导入 → OCR → 压缩 → 水印 → 输出
    """

    def __init__(self, files: list[str], workflow: dict, output_dir: str) -> None:
        super().__init__()
        self.files = files
        self.workflow = workflow
        self.output_dir = Path(output_dir)

    def run_task(self) -> list[dict]:
        results = []
        total = len(self.files)
        max_attempts = _workflow_max_attempts()

        for idx, file_path in enumerate(self.files):
            if self.is_cancelled():
                break

            result = {"file": file_path, "steps": [], "output": None, "error": None}
            current_path = file_path

            try:
                self.emit_message(f"[{idx+1}/{total}] 处理：{Path(file_path).name}")

                # ── 步骤1：OCR（如启用）──────────
                if self.workflow.get("ocr_enabled"):
                    self.emit_message("  → OCR 识别...")
                    try:
                        def _do_ocr():
                            nonlocal current_path
                            from core.ocr.engine import OCRManager, OCROptions
                            manager = OCRManager(engine_name=settings_mgr.ocr.engine)
                            if not manager.is_available:
                                raise RuntimeError("OCR 引擎不可用")
                            options = OCROptions(
                                languages=self.workflow.get("ocr_languages", ["ch", "en"])
                            )
                            ocr_results = manager.ocr_pdf(
                                current_path, options, should_cancel=self.is_cancelled
                            )
                            if self.is_cancelled():
                                raise RuntimeError("已取消")
                            ocr_out = self.output_dir / f"{Path(current_path).stem}_ocr.pdf"
                            current_path = str(
                                manager.generate_searchable_pdf(
                                    current_path,
                                    ocr_results,
                                    ocr_out,
                                    should_cancel=self.is_cancelled,
                                    cleanup_on_cancel=True,
                                )
                            )
                            if self.is_cancelled():
                                raise RuntimeError("已取消")

                        run_with_retry(
                            _do_ocr,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → OCR 失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append("OCR ✓")
                    except Exception as e:
                        result["steps"].append(f"OCR ✗ ({e})")
                        logger.warning(f"OCR失败: {e}")

                # ── 步骤2：压缩（如启用）──────────
                if self.workflow.get("compress_enabled"):
                    self.emit_message("  → 压缩...")
                    try:
                        def _do_compress():
                            nonlocal current_path
                            from core.pdf.processor import PDFCompressor, CompressOptions
                            compress_out = self.output_dir / f"{Path(current_path).stem}_compressed.pdf"
                            options = CompressOptions(
                                output_path=compress_out,
                                mode=self.workflow.get("compress_mode", "balanced"),
                            )
                            current_path = str(
                                PDFCompressor().compress(
                                    current_path,
                                    options,
                                    should_cancel=self.is_cancelled,
                                    cleanup_on_cancel=True,
                                ).path
                            )
                            if self.is_cancelled():
                                raise RuntimeError("已取消")

                        run_with_retry(
                            _do_compress,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → 压缩失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append("压缩 ✓")
                    except Exception as e:
                        result["steps"].append(f"压缩 ✗ ({e})")
                        logger.warning(f"压缩失败: {e}")

                # ── 步骤3：添加水印（如启用）──────
                if self.workflow.get("watermark_enabled"):
                    self.emit_message("  → 添加水印...")
                    try:
                        def _do_watermark():
                            nonlocal current_path
                            from core.pdf.processor import PDFWatermarker, WatermarkOptions
                            wm_out = self.output_dir / f"{Path(current_path).stem}_wm.pdf"
                            options = WatermarkOptions(
                                text=self.workflow.get("watermark_text", "PDF Studio"),
                                opacity=self.workflow.get("watermark_opacity", 0.3),
                                rotation=self.workflow.get("watermark_rotation", 45.0),
                            )
                            current_path = str(
                                PDFWatermarker().add_text_watermark(
                                    current_path,
                                    wm_out,
                                    options,
                                    should_cancel=self.is_cancelled,
                                    cleanup_on_cancel=True,
                                )
                            )
                            if self.is_cancelled():
                                raise RuntimeError("已取消")

                        run_with_retry(
                            _do_watermark,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → 水印失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append("水印 ✓")
                    except Exception as e:
                        result["steps"].append(f"水印 ✗ ({e})")
                        logger.warning(f"水印失败: {e}")

                # ── 步骤4：添加页码（如启用）──────
                if self.workflow.get("page_numbers_enabled"):
                    self.emit_message("  → 添加页码...")
                    try:
                        def _do_page_numbers():
                            nonlocal current_path
                            from core.pdf.processor import PDFPageNumberer, PageNumberOptions
                            pn_out = self.output_dir / f"{Path(current_path).stem}_paged.pdf"
                            options = PageNumberOptions(
                                position=self.workflow.get("page_number_position", "bottom_center"),
                                format_str=self.workflow.get("page_number_format", "{n}"),
                            )
                            current_path = str(
                                PDFPageNumberer().add_page_numbers(current_path, pn_out, options)
                            )

                        run_with_retry(
                            _do_page_numbers,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → 页码失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append("页码 ✓")
                    except Exception as e:
                        result["steps"].append(f"页码 ✗ ({e})")
                        logger.warning(f"页码失败: {e}")

                # ── 步骤5：加密（如启用）──────────
                if self.workflow.get("encrypt_enabled"):
                    self.emit_message("  → 加密...")
                    try:
                        def _do_encrypt():
                            nonlocal current_path
                            from core.pdf.processor import PDFEncryptor
                            enc_out = self.output_dir / f"{Path(current_path).stem}_enc.pdf"
                            PDFEncryptor().encrypt(
                                current_path,
                                enc_out,
                                user_password=self.workflow.get("encrypt_password", ""),
                            )
                            current_path = str(enc_out)

                        run_with_retry(
                            _do_encrypt,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → 加密失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append("加密 ✓")
                    except Exception as e:
                        result["steps"].append(f"加密 ✗ ({e})")
                        logger.warning(f"加密失败: {e}")

                # ── 步骤6：转 PNG（如启用）────────
                if self.workflow.get("png_enabled"):
                    self.emit_message("  → 导出 PNG...")
                    try:
                        def _do_png():
                            from core.image.converter import PDFToImageConverter, PDFToImageOptions
                            png_dir = self.output_dir / Path(current_path).stem
                            png_dir.mkdir(parents=True, exist_ok=True)
                            options = PDFToImageOptions(
                                output_dir=png_dir,
                                format="PNG",
                                dpi=self.workflow.get("png_dpi", 150),
                            )
                            return PDFToImageConverter().convert(
                                current_path,
                                options,
                                should_cancel=self.is_cancelled,
                            )

                        outputs = run_with_retry(
                            _do_png,
                            max_attempts=max_attempts,
                            on_retry=lambda n, e: self.emit_message(
                                f"  → PNG 失败 ({e})，重试 {n}/{max_attempts - 1}..."
                            ),
                        )
                        result["steps"].append(f"PNG ✓ ({len(outputs)} 张)")
                    except Exception as e:
                        result["steps"].append(f"PNG ✗ ({e})")
                        logger.warning(f"PNG导出失败: {e}")

                # ── 最终：复制到输出目录 ──────────
                self.output_dir.mkdir(parents=True, exist_ok=True)
                final_name = f"{Path(file_path).stem}_processed.pdf"
                final_out = self.output_dir / final_name
                if self.is_cancelled():
                    break
                if Path(current_path) != final_out:
                    import shutil
                    shutil.copy2(current_path, final_out)

                result["output"] = str(final_out)
                result["steps"].append("归档 ✓")

            except Exception as e:
                result["error"] = str(e)
                logger.error(f"批处理文件失败 {file_path}: {e}")

            results.append(result)
            self.emit_progress(idx + 1, total)

        return results


class BatchPage(QWidget):
    """批处理工作流中心页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("batchPage")
        self._files: list[str] = []
        self._current_worker: Optional[BatchWorkflowWorker] = None
        self._history_entries = []
        self._setup_ui()

    def _setup_ui(self):
        from PyQt6.QtWidgets import QSplitter
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("批处理工作流中心"))
        root.addWidget(wps_hint_label("batch"))
        root.addWidget(CaptionLabel("配置自动化工作流：OCR · 压缩 · 水印 · 页码 · 加密 · 转 PNG · 归档"))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([460, 500])
        root.addWidget(splitter, 1)

    def _build_left(self) -> QWidget:
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)
        scroll.setWidget(container)

        # 文件导入
        import_card = CardWidget()
        imp_l = QVBoxLayout(import_card)
        imp_l.setContentsMargins(16, 14, 16, 14)
        imp_l.setSpacing(10)
        imp_l.addWidget(StrongBodyLabel("导入文件"))

        btn_row = QHBoxLayout()
        add_btn = PushButton(FluentIcon.DOCUMENT, "添加文件")
        add_btn.clicked.connect(self._add_files)
        folder_btn = PushButton(FluentIcon.FOLDER, "添加文件夹")
        folder_btn.clicked.connect(self._add_folder)
        clear_btn = PushButton("清空")
        clear_btn.clicked.connect(self._clear_files)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(folder_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        imp_l.addLayout(btn_row)

        self._file_list = QListWidget()
        self._file_list.setFixedHeight(150)
        apply_list_widget_style(self._file_list)
        imp_l.addWidget(self._file_list)
        self._file_count = CaptionLabel("共 0 个文件")
        imp_l.addWidget(self._file_count)
        layout.addWidget(import_card)

        # 工作流配置
        wf_card = CardWidget()
        wf_l = QVBoxLayout(wf_card)
        wf_l.setContentsMargins(16, 14, 16, 14)
        wf_l.setSpacing(10)
        wf_l.addWidget(StrongBodyLabel("工作流步骤"))
        wf_l.addWidget(CaptionLabel("勾选需要执行的步骤（按顺序自动执行）"))

        # OCR 步骤
        self._step_ocr = CheckBox("① OCR 识别 → 生成可搜索PDF")
        wf_l.addWidget(self._step_ocr)
        ocr_lang_row = QHBoxLayout()
        ocr_lang_row.addSpacing(24)
        ocr_lang_row.addWidget(CaptionLabel("语言："))
        self._ocr_lang = StudioComboBox()
        self._ocr_lang.addItems(["中文+英文", "仅英文", "中文+日文"])
        ocr_lang_row.addWidget(self._ocr_lang)
        ocr_lang_row.addStretch()
        wf_l.addLayout(ocr_lang_row)

        # 压缩步骤
        self._step_compress = CheckBox("② PDF 压缩")
        wf_l.addWidget(self._step_compress)
        compress_row = QHBoxLayout()
        compress_row.addSpacing(24)
        compress_row.addWidget(CaptionLabel("模式："))
        self._compress_mode = StudioComboBox()
        self._compress_mode.addItems(["高质量", "均衡模式", "极限压缩"])
        self._compress_mode.setCurrentIndex(1)
        compress_row.addWidget(self._compress_mode)
        compress_row.addStretch()
        wf_l.addLayout(compress_row)

        # 水印步骤
        self._step_watermark = CheckBox("③ 添加文字水印")
        wf_l.addWidget(self._step_watermark)
        wm_row = QHBoxLayout()
        wm_row.addSpacing(24)
        wm_row.addWidget(CaptionLabel("水印文字："))
        self._wm_text = LineEdit()
        self._wm_text.setPlaceholderText("水印内容")
        wm_row.addWidget(self._wm_text, 1)
        wf_l.addLayout(wm_row)

        # 页码步骤
        self._step_pagenum = CheckBox("④ 添加页码")
        wf_l.addWidget(self._step_pagenum)
        pn_row = QHBoxLayout()
        pn_row.addSpacing(24)
        pn_row.addWidget(CaptionLabel("位置："))
        self._pn_position = StudioComboBox()
        self._pn_position.addItems(["底部居中", "底部居右", "底部居左", "顶部居中"])
        pn_row.addWidget(self._pn_position)
        pn_row.addStretch()
        wf_l.addLayout(pn_row)

        # 加密步骤
        self._step_encrypt = CheckBox("⑤ PDF 加密")
        wf_l.addWidget(self._step_encrypt)
        enc_row = QHBoxLayout()
        enc_row.addSpacing(24)
        enc_row.addWidget(CaptionLabel("密码："))
        self._enc_password = LineEdit()
        self._enc_password.setPlaceholderText("打开密码")
        enc_row.addWidget(self._enc_password, 1)
        wf_l.addLayout(enc_row)

        # PNG 导出步骤
        self._step_png = CheckBox("⑥ 导出 PNG 图片")
        wf_l.addWidget(self._step_png)
        png_row = QHBoxLayout()
        png_row.addSpacing(24)
        png_row.addWidget(CaptionLabel("DPI："))
        self._png_dpi = SpinBox()
        self._png_dpi.setRange(72, 600)
        self._png_dpi.setValue(150)
        png_row.addWidget(self._png_dpi)
        png_row.addStretch()
        wf_l.addLayout(png_row)

        layout.addWidget(wf_card)

        # 输出设置
        out_card = CardWidget()
        out_l = QVBoxLayout(out_card)
        out_l.setContentsMargins(16, 14, 16, 14)
        out_l.setSpacing(10)
        out_l.addWidget(StrongBodyLabel("输出目录"))
        out_row = QHBoxLayout()
        self._out_dir = LineEdit()
        self._out_dir.setPlaceholderText("批处理结果输出目录")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._out_dir.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._out_dir.text()
        ))
        out_row.addWidget(self._out_dir, 1)
        out_row.addWidget(b)
        out_l.addLayout(out_row)
        layout.addWidget(out_card)

        # 执行按钮
        self._run_btn = PrimaryPushButton(FluentIcon.CALORIES, "启动批处理")
        self._run_btn.setFixedHeight(40)
        self._run_btn.clicked.connect(self._start)
        layout.addWidget(self._run_btn)

        self._progress = TaskProgressCard("准备就绪")
        self._progress.setVisible(False)
        self._progress.cancelRequested.connect(self._cancel)
        layout.addWidget(self._progress)
        layout.addStretch()

        return scroll

    def _build_right(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        tabs = QTabWidget()

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_header = QHBoxLayout()
        log_header.addWidget(StrongBodyLabel("执行日志"))
        clear_log_btn = PushButton("清空")
        clear_log_btn.setFixedWidth(56)
        clear_log_btn.clicked.connect(lambda: self._log.clear())
        log_header.addStretch()
        log_header.addWidget(clear_log_btn)
        log_layout.addLayout(log_header)
        self._log = TextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("批处理日志将显示在此处...")
        log_layout.addWidget(self._log, 1)
        tabs.addTab(log_tab, "执行日志")

        hist_tab = QWidget()
        hist_layout = QVBoxLayout(hist_tab)
        hist_layout.setContentsMargins(0, 0, 0, 0)
        hist_header = QHBoxLayout()
        hist_header.addWidget(StrongBodyLabel("工作流历史"))
        apply_btn = PushButton("应用配置")
        apply_btn.setFixedWidth(80)
        apply_btn.clicked.connect(self._apply_selected_history)
        del_btn = PushButton("删除")
        del_btn.setFixedWidth(56)
        del_btn.clicked.connect(self._delete_selected_history)
        clear_hist_btn = PushButton("清空")
        clear_hist_btn.setFixedWidth(56)
        clear_hist_btn.clicked.connect(self._clear_history)
        hist_header.addStretch()
        hist_header.addWidget(apply_btn)
        hist_header.addWidget(del_btn)
        hist_header.addWidget(clear_hist_btn)
        hist_layout.addLayout(hist_header)
        hist_layout.addWidget(CaptionLabel(
            "双击条目可快速恢复步骤勾选与参数（不含文件列表与加密密码）"
        ))
        self._history_list = QListWidget()
        apply_list_widget_style(self._history_list)
        self._history_list.itemDoubleClicked.connect(self._apply_selected_history)
        hist_layout.addWidget(self._history_list, 1)
        tabs.addTab(hist_tab, "历史记录")

        layout.addWidget(tabs, 1)
        self._refresh_history_list()
        return panel

    # ─────────────────────────────────────────
    # 文件管理
    # ─────────────────────────────────────────

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择PDF文件", "", "PDF 文件 (*.pdf)"
        )
        for f in files:
            if f not in self._files:
                self._files.append(f)
                self._file_list.addItem(Path(f).name)
        self._file_count.setText(f"共 {len(self._files)} 个文件")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            pdfs = collect_files(folder, {".pdf"})
            for p in pdfs:
                if str(p) not in self._files:
                    self._files.append(str(p))
                    self._file_list.addItem(p.name)
            self._file_count.setText(f"共 {len(self._files)} 个文件")

    def _clear_files(self):
        self._files.clear()
        self._file_list.clear()
        self._file_count.setText("共 0 个文件")

    def _refresh_history_list(self) -> None:
        self._history_entries = WorkflowHistoryStore.load()
        self._history_list.clear()
        if not self._history_entries:
            self._history_list.addItem("（暂无历史，可在设置中开启「保存工作流历史」）")
            item = self._history_list.item(0)
            if item:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            return
        for entry in self._history_entries:
            item = QListWidgetItem(entry.display_text())
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(entry.output_dir)
            self._history_list.addItem(item)

    def _selected_history_entry(self):
        row = self._history_list.currentRow()
        if row < 0 or row >= len(self._history_entries):
            return None
        return self._history_entries[row]

    def _apply_workflow_dict(self, wf: dict) -> None:
        self._step_ocr.setChecked(wf.get("ocr_enabled", False))
        lang_rev = {
            ("ch", "en"): "中文+英文",
            ("en",): "仅英文",
            ("ch", "japan"): "中文+日文",
        }
        langs = tuple(wf.get("ocr_languages", ["ch", "en"]))
        for key, label in lang_rev.items():
            if tuple(key) == langs:
                idx = self._ocr_lang.findText(label)
                if idx >= 0:
                    self._ocr_lang.setCurrentIndex(idx)
                break
        self._step_compress.setChecked(wf.get("compress_enabled", False))
        mode_rev = {
            "high_quality": "高质量",
            "balanced": "均衡模式",
            "max_compress": "极限压缩",
        }
        mode_label = mode_rev.get(wf.get("compress_mode", "balanced"), "均衡模式")
        idx = self._compress_mode.findText(mode_label)
        if idx >= 0:
            self._compress_mode.setCurrentIndex(idx)
        self._step_watermark.setChecked(wf.get("watermark_enabled", False))
        self._wm_text.setText(wf.get("watermark_text", ""))
        self._step_pagenum.setChecked(wf.get("page_numbers_enabled", False))
        pn_rev = {
            "bottom_center": "底部居中",
            "bottom_right": "底部居右",
            "bottom_left": "底部居左",
            "top_center": "顶部居中",
        }
        pn_label = pn_rev.get(wf.get("page_number_position", "bottom_center"), "底部居中")
        idx = self._pn_position.findText(pn_label)
        if idx >= 0:
            self._pn_position.setCurrentIndex(idx)
        self._step_encrypt.setChecked(wf.get("encrypt_enabled", False))
        self._enc_password.clear()
        if wf.get("encrypt_enabled"):
            show_info(self, "历史记录不含密码，启用加密时请重新输入")
        self._step_png.setChecked(wf.get("png_enabled", False))
        self._png_dpi.setValue(int(wf.get("png_dpi", 150)))

    def _apply_selected_history(self) -> None:
        entry = self._selected_history_entry()
        if not entry:
            show_warning(self, "请先选择一条历史记录")
            return
        self._apply_workflow_dict(entry.workflow)
        if entry.output_dir:
            self._out_dir.setText(entry.output_dir)
        show_info(self, "已应用历史工作流配置")

    def _delete_selected_history(self) -> None:
        entry = self._selected_history_entry()
        if not entry:
            show_warning(self, "请先选择一条历史记录")
            return
        WorkflowHistoryStore.delete(entry.id)
        self._refresh_history_list()

    def _clear_history(self) -> None:
        WorkflowHistoryStore.clear()
        self._refresh_history_list()
        show_info(self, "工作流历史已清空")

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_history_list()

    # ─────────────────────────────────────────
    # 执行
    # ─────────────────────────────────────────

    def _start(self):
        if not self._files:
            show_warning(self, "请先添加文件")
            return
        out_dir = self._out_dir.text().strip()
        if not out_dir:
            show_warning(self, "请设置输出目录")
            return

        steps_enabled = (
            self._step_ocr.isChecked() or
            self._step_compress.isChecked() or
            self._step_watermark.isChecked() or
            self._step_pagenum.isChecked() or
            self._step_encrypt.isChecked() or
            self._step_png.isChecked()
        )
        if not steps_enabled:
            show_warning(self, "请至少勾选一个工作流步骤")
            return
        if self._step_encrypt.isChecked() and not self._enc_password.text().strip():
            show_warning(self, "启用加密时请设置密码")
            return

        lang_map = {"中文+英文": ["ch", "en"], "仅英文": ["en"], "中文+日文": ["ch", "japan"]}
        mode_map = {"高质量": "high_quality", "均衡模式": "balanced", "极限压缩": "max_compress"}
        pn_pos_map = {
            "底部居中": "bottom_center",
            "底部居右": "bottom_right",
            "底部居左": "bottom_left",
            "顶部居中": "top_center",
        }

        workflow = {
            "ocr_enabled": self._step_ocr.isChecked(),
            "ocr_languages": lang_map.get(self._ocr_lang.currentText(), ["ch", "en"]),
            "compress_enabled": self._step_compress.isChecked(),
            "compress_mode": mode_map.get(self._compress_mode.currentText(), "balanced"),
            "watermark_enabled": self._step_watermark.isChecked(),
            "watermark_text": self._wm_text.text().strip() or "PDF Studio",
            "page_numbers_enabled": self._step_pagenum.isChecked(),
            "page_number_position": pn_pos_map.get(
                self._pn_position.currentText(), "bottom_center"
            ),
            "encrypt_enabled": self._step_encrypt.isChecked(),
            "encrypt_password": self._enc_password.text(),
            "png_enabled": self._step_png.isChecked(),
            "png_dpi": self._png_dpi.value(),
        }

        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._log.clear()
        self._log.append(f"开始批处理 {len(self._files)} 个文件...")
        self._last_workflow = workflow

        worker = BatchWorkflowWorker(self._files, workflow, out_dir)
        self._current_worker = worker
        worker.signals.progress.connect(self._progress.update_progress)
        worker.signals.message.connect(self._on_log)
        worker.signals.finished.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(lambda: self._progress.set_cancelled())
        submit_worker(worker)

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_done(self, results: list):
        self._run_btn.setEnabled(True)
        ok = sum(1 for r in results if not r.get("error"))
        self._progress.set_finished(True, f"完成 {ok}/{len(results)}")
        self._log.append(f"\n✓ 批处理完成：{ok}/{len(results)} 成功")
        for r in results:
            status = "✓" if not r.get("error") else f"✗ {r['error']}"
            steps = " → ".join(r.get("steps", []))
            self._log.append(f"  {status}  {Path(r['file']).name}  [{steps}]")
        if hasattr(self, "_last_workflow"):
            WorkflowHistoryStore.append_from_run(
                self._last_workflow,
                self._out_dir.text().strip(),
                len(self._files),
                results,
            )
            self._refresh_history_list()
        if ok > 0:
            finish_output_task(self, "批处理完成", self._out_dir.text())

    def _on_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._progress.set_finished(False, msg)
        self._log.append(f"✗ 错误：{msg}")
        show_error(self, "批处理失败", msg)

    def _cancel(self):
        if self._current_worker:
            self._current_worker.request_cancel()
            self._run_btn.setEnabled(True)
