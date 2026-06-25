"""
PDF Studio - PDF 高级工具
去水印 · 表单 · 签名 · 涂黑脱敏
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTabWidget,
    QScrollArea, QFormLayout, QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    ScrollArea, TitleLabel, CaptionLabel, PrimaryPushButton, PushButton,
    LineEdit, SpinBox, StrongBodyLabel, FluentIcon, CheckBox, BodyLabel,
)

from app.widgets.combo_box import StudioComboBox
from app.widgets.list_styles import apply_list_widget_style
from app.config.settings import settings_mgr
from app.widgets.pdf_page_view import PDFPageView
from app.widgets.common import (
    DropZone, TaskProgressCard, show_success, show_error, show_warning, show_info,
    finish_output_task, wps_hint_label,
)
from app.workers.base_worker import (
    submit_worker,
    PDFWatermarkDetectWorker, PDFWatermarkRemoveWorker,
    PDFFormListWorker, PDFFormFillWorker, PDFSignatureWorker,
    PDFRedactWorker, PDFPageRenderWorker,
    PDFTextOverlayWorker, PDFMetadataWorker,
)
from core.pdf.extras import FormFieldInfo, SignatureOptions, RedactRegion, TextOverlayItem
from core.pdf.processor import PDFReader as PDFReaderUtil


class ToolsPage(ScrollArea):
    """PDF 高级工具页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolsPage")
        self._wm_path: Optional[str] = None
        self._wm_password = ""
        self._wm_candidates = []
        self._form_path: Optional[str] = None
        self._form_password = ""
        self._form_fields: list[FormFieldInfo] = []
        self._form_widgets: dict[str, QWidget] = {}
        self._sig_path: Optional[str] = None
        self._sig_password = ""
        self._wm_checkboxes: list = []
        self._redact_path: Optional[str] = None
        self._redact_password = ""
        self._redact_page_count = 0
        self._redact_regions: list[RedactRegion] = []
        self._type_path: Optional[str] = None
        self._meta_path: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel("PDF 高级工具"))
        root.addWidget(wps_hint_label("tools"))
        root.addWidget(CaptionLabel(
            "去水印 · 表单填写 · 图片签名 · 涂黑脱敏 · 打字机 · 文档信息"
        ))

        tabs = QTabWidget()
        tabs.addTab(self._build_watermark_tab(), "去水印")
        tabs.addTab(self._build_form_tab(), "表单填写")
        tabs.addTab(self._build_signature_tab(), "电子签名")
        tabs.addTab(self._build_redact_tab(), "涂黑脱敏")
        tabs.addTab(self._build_typewriter_tab(), "打字机")
        tabs.addTab(self._build_metadata_tab(), "文档信息")
        root.addWidget(tabs)
        root.addStretch()

    # ── 去水印 ────────────────────────────────

    def _build_watermark_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放 PDF 以检测水印")
        drop.filesDropped.connect(self._wm_load)
        layout.addWidget(drop)
        self._wm_label = CaptionLabel("")
        self._wm_label.setStyleSheet("color:#888;")
        layout.addWidget(self._wm_label)

        detect_btn = PushButton(FluentIcon.SEARCH, "检测疑似水印")
        detect_btn.clicked.connect(self._wm_detect)
        layout.addWidget(detect_btn)

        self._wm_checks_host = QVBoxLayout()
        self._wm_checks_host.setSpacing(6)
        layout.addLayout(self._wm_checks_host)

        self._wm_hint = BodyLabel(
            "说明：仅适用于多页重复出现的图片或文字水印；复杂水印可能无法完全去除。"
        )
        self._wm_hint.setStyleSheet("color:#888;")
        self._wm_hint.setWordWrap(True)
        layout.addWidget(self._wm_hint)

        out_row = QHBoxLayout()
        self._wm_out = LineEdit()
        self._wm_out.setPlaceholderText("输出 PDF 路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._wm_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "no_watermark.pdf", "PDF (*.pdf)")[0]
            or self._wm_out.text()
        ))
        out_row.addWidget(self._wm_out, 1)
        out_row.addWidget(b)
        layout.addLayout(out_row)

        run_btn = PrimaryPushButton(FluentIcon.DELETE, "移除选中水印")
        run_btn.clicked.connect(self._wm_remove)
        layout.addWidget(run_btn)

        self._wm_progress = TaskProgressCard("准备就绪")
        self._wm_progress.setVisible(False)
        layout.addWidget(self._wm_progress)
        layout.addStretch()
        return w

    def _wm_load(self, paths: list[str]) -> None:
        if paths:
            self._wm_path = paths[0]
            self._wm_password = ""
            self._wm_label.setText(Path(paths[0]).name)
            self._wm_out.setText(str(
                Path(paths[0]).with_name(f"{Path(paths[0]).stem}_no_wm.pdf")
            ))

    def _wm_detect(self) -> None:
        if not self._wm_path:
            show_warning(self, "请先导入 PDF")
            return
        w = PDFWatermarkDetectWorker(self._wm_path, self._wm_password)
        w.signals.finished.connect(self._wm_on_detected)
        w.signals.error.connect(lambda m: show_error(self, "检测失败", m))
        submit_worker(w)

    def _wm_on_detected(self, candidates) -> None:
        self._wm_candidates = candidates
        while self._wm_checks_host.count():
            item = self._wm_checks_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._wm_checkboxes = []
        if not candidates:
            layout = self._wm_checks_host
            lbl = CaptionLabel("未检测到明显的重复水印，可尝试手动指定文字模式。")
            lbl.setStyleSheet("color:#888;")
            layout.addWidget(lbl)
            show_info(self, "未检测到重复水印")
            return
        for c in candidates:
            cb = CheckBox(c.label)
            cb.setChecked(True)
            self._wm_checks_host.addWidget(cb)
            self._wm_checkboxes.append((cb, c))
        show_success(self, f"检测到 {len(candidates)} 项疑似水印")

    def _wm_remove(self) -> None:
        if not self._wm_path:
            show_warning(self, "请先导入 PDF")
            return
        out = self._wm_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        image_xrefs: list[int] = []
        text_patterns: list[str] = []
        for cb, c in getattr(self, "_wm_checkboxes", []):
            if cb.isChecked():
                if c.kind == "image":
                    image_xrefs.append(int(c.key))
                else:
                    text_patterns.append(c.key)
        if not image_xrefs and not text_patterns:
            show_warning(self, "请至少选择一项水印，或先执行检测")
            return
        self._wm_progress.setVisible(True)
        w = PDFWatermarkRemoveWorker(
            self._wm_path, out, image_xrefs, text_patterns, self._wm_password,
        )
        w.signals.progress.connect(self._wm_progress.update_progress)
        w.signals.finished.connect(lambda r: (
            self._wm_progress.set_finished(
                True,
                f"已移除图片 {r.removed_images} 处，文字 {r.removed_text_blocks} 处",
            ),
            finish_output_task(self, "去水印完成", r.path),
        ))
        w.signals.error.connect(lambda m: (
            self._wm_progress.set_finished(False, m),
            show_error(self, "失败", m),
        ))
        submit_worker(w)

    # ── 表单填写 ──────────────────────────────

    def _build_form_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放含表单字段的 PDF")
        drop.filesDropped.connect(self._form_load)
        layout.addWidget(drop)
        self._form_label = CaptionLabel("")
        self._form_label.setStyleSheet("color:#888;")
        layout.addWidget(self._form_label)

        scan_btn = PushButton(FluentIcon.SEARCH, "扫描表单字段")
        scan_btn.clicked.connect(self._form_scan)
        layout.addWidget(scan_btn)

        self._form_scroll = QScrollArea()
        self._form_scroll.setWidgetResizable(True)
        self._form_fields_widget = QWidget()
        self._form_fields_layout = QFormLayout(self._form_fields_widget)
        self._form_scroll.setWidget(self._form_fields_widget)
        self._form_scroll.setMinimumHeight(200)
        layout.addWidget(self._form_scroll)

        out_row = QHBoxLayout()
        self._form_out = LineEdit()
        self._form_out.setPlaceholderText("输出 PDF 路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._form_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "filled.pdf", "PDF (*.pdf)")[0]
            or self._form_out.text()
        ))
        out_row.addWidget(self._form_out, 1)
        out_row.addWidget(b)
        layout.addLayout(out_row)

        fill_btn = PrimaryPushButton(FluentIcon.EDIT, "填写并保存")
        fill_btn.clicked.connect(self._form_fill)
        layout.addWidget(fill_btn)

        self._form_progress = TaskProgressCard("准备就绪")
        self._form_progress.setVisible(False)
        layout.addWidget(self._form_progress)
        layout.addStretch()
        return w

    def _form_load(self, paths: list[str]) -> None:
        if paths:
            self._form_path = paths[0]
            self._form_label.setText(Path(paths[0]).name)
            self._form_out.setText(str(
                Path(paths[0]).with_name(f"{Path(paths[0]).stem}_filled.pdf")
            ))

    def _form_scan(self) -> None:
        if not self._form_path:
            show_warning(self, "请先导入 PDF")
            return
        w = PDFFormListWorker(self._form_path, self._form_password)
        w.signals.finished.connect(self._form_on_fields)
        w.signals.error.connect(lambda m: show_error(self, "扫描失败", m))
        submit_worker(w)

    def _form_on_fields(self, fields: list[FormFieldInfo]) -> None:
        self._form_fields = fields
        self._form_widgets.clear()
        while self._form_fields_layout.rowCount():
            label_item, field_item = self._form_fields_layout.takeRow(0)
            for item in (label_item, field_item):
                if item and item.widget():
                    item.widget().deleteLater()
        if not fields:
            show_warning(self, "该 PDF 未检测到 AcroForm 表单字段")
            return
        for f in fields:
            widget = self._form_field_widget(f)
            label = f"{f.name}（第{f.page_index + 1}页 · {f.field_type}）"
            self._form_fields_layout.addRow(label, widget)
            self._form_widgets[f.name] = widget
        show_success(self, f"发现 {len(fields)} 个表单字段")

    def _form_field_widget(self, field: FormFieldInfo) -> QWidget:
        ftype = (field.field_type or "").lower()
        if "check" in ftype or "radio" in ftype:
            cb = CheckBox(field.name)
            cb.setChecked(str(field.value).lower() in ("yes", "true", "1", "on"))
            return cb
        if ("combo" in ftype or "list" in ftype) and field.choices:
            combo = StudioComboBox()
            combo.addItems(field.choices)
            if field.value and field.value in field.choices:
                combo.setCurrentText(field.value)
            elif field.choices:
                combo.setCurrentIndex(0)
            return combo
        edit = LineEdit()
        edit.setText(field.value)
        edit.setPlaceholderText(field.field_type)
        return edit

    @staticmethod
    def _form_widget_value(field: FormFieldInfo, widget: QWidget) -> str:
        if isinstance(widget, CheckBox):
            return "Yes" if widget.isChecked() else "Off"
        if isinstance(widget, StudioComboBox):
            return widget.currentText()
        if isinstance(widget, LineEdit):
            return widget.text()
        return ""

    def _form_fill(self) -> None:
        if not self._form_path or not self._form_widgets:
            show_warning(self, "请先扫描表单字段")
            return
        out = self._form_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        values = {
            name: self._form_widget_value(
                next(f for f in self._form_fields if f.name == name), w
            )
            for name, w in self._form_widgets.items()
        }
        self._form_progress.setVisible(True)
        w = PDFFormFillWorker(self._form_path, out, values, self._form_password)
        w.signals.finished.connect(lambda p: (
            self._form_progress.set_finished(True),
            finish_output_task(self, "表单已保存", p),
        ))
        w.signals.error.connect(lambda m: (
            self._form_progress.set_finished(False, m),
            show_error(self, "填写失败", m),
        ))
        submit_worker(w)

    # ── 电子签名 ──────────────────────────────

    def _build_signature_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放待签名的 PDF")
        drop.filesDropped.connect(self._sig_load)
        layout.addWidget(drop)
        self._sig_label = CaptionLabel("")
        self._sig_label.setStyleSheet("color:#888;")
        layout.addWidget(self._sig_label)

        card = QWidget()
        form = QFormLayout(card)

        img_row = QHBoxLayout()
        self._sig_image = LineEdit()
        self._sig_image.setPlaceholderText("签名图片 PNG/JPG（建议透明背景）")
        img_b = PushButton("浏览")
        img_b.clicked.connect(self._sig_browse_image)
        img_row.addWidget(self._sig_image, 1)
        img_row.addWidget(img_b)
        form.addRow("签名图片：", img_row)

        self._sig_page = SpinBox()
        self._sig_page.setRange(-1, 9999)
        self._sig_page.setValue(-1)
        self._sig_page.setSpecialValueText("最后一页")
        form.addRow("目标页（-1=末页）：", self._sig_page)

        self._sig_pos = StudioComboBox()
        self._sig_pos.addItems(["右下", "左下", "底部居中"])
        form.addRow("位置：", self._sig_pos)

        self._sig_w = SpinBox()
        self._sig_w.setRange(40, 400)
        self._sig_w.setValue(120)
        form.addRow("宽度（pt）：", self._sig_w)

        self._sig_h = SpinBox()
        self._sig_h.setRange(20, 200)
        self._sig_h.setValue(48)
        form.addRow("高度（pt）：", self._sig_h)

        layout.addWidget(card)

        hint = BodyLabel("图片签名为视觉标记，不具备 CA 数字证书法律效力。")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        out_row = QHBoxLayout()
        self._sig_out = LineEdit()
        self._sig_out.setPlaceholderText("输出 PDF 路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._sig_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "signed.pdf", "PDF (*.pdf)")[0]
            or self._sig_out.text()
        ))
        out_row.addWidget(self._sig_out, 1)
        out_row.addWidget(b)
        layout.addLayout(out_row)

        btn = PrimaryPushButton(FluentIcon.PIN, "插入签名")
        btn.clicked.connect(self._sig_apply)
        layout.addWidget(btn)

        self._sig_progress = TaskProgressCard("准备就绪")
        self._sig_progress.setVisible(False)
        layout.addWidget(self._sig_progress)
        layout.addStretch()
        return w

    def _sig_load(self, paths: list[str]) -> None:
        if paths:
            self._sig_path = paths[0]
            self._sig_label.setText(Path(paths[0]).name)
            self._sig_out.setText(str(
                Path(paths[0]).with_name(f"{Path(paths[0]).stem}_signed.pdf")
            ))

    def _sig_browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择签名图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp);;所有文件 (*.*)",
        )
        if path:
            self._sig_image.setText(path)

    def _sig_apply(self) -> None:
        if not self._sig_path:
            show_warning(self, "请先导入 PDF")
            return
        img = self._sig_image.text().strip()
        if not img or not Path(img).is_file():
            show_warning(self, "请选择签名图片")
            return
        out = self._sig_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        pos_map = {"右下": "bottom_right", "左下": "bottom_left", "底部居中": "bottom_center"}
        options = SignatureOptions(
            image_path=Path(img),
            page_index=self._sig_page.value(),
            width=float(self._sig_w.value()),
            height=float(self._sig_h.value()),
            position=pos_map.get(self._sig_pos.currentText(), "bottom_right"),
        )
        self._sig_progress.setVisible(True)
        w = PDFSignatureWorker(self._sig_path, out, options, self._sig_password)
        w.signals.finished.connect(lambda p: (
            self._sig_progress.set_finished(True),
            finish_output_task(self, "签名已插入", p),
        ))
        w.signals.error.connect(lambda m: (
            self._sig_progress.set_finished(False, m),
            show_error(self, "失败", m),
        ))
        submit_worker(w)

    # ── 涂黑脱敏 ──────────────────────────────

    def _build_redact_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放需要脱敏的 PDF")
        drop.filesDropped.connect(self._redact_load)
        layout.addWidget(drop)
        self._redact_label = CaptionLabel("")
        self._redact_label.setStyleSheet("color:#888;")
        layout.addWidget(self._redact_label)

        hint = BodyLabel(
            "在下方页面预览中框选涂黑区域；也可输入文字关键词批量涂黑（逗号分隔）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        page_row = QHBoxLayout()
        page_row.addWidget(CaptionLabel("预览页："))
        self._redact_page_spin = SpinBox()
        self._redact_page_spin.setRange(1, 1)
        self._redact_page_spin.valueChanged.connect(self._redact_on_page_changed)
        page_row.addWidget(self._redact_page_spin)
        prev_btn = PushButton("上一页")
        prev_btn.clicked.connect(lambda: self._redact_page_spin.setValue(
            max(1, self._redact_page_spin.value() - 1)
        ))
        next_btn = PushButton("下一页")
        next_btn.clicked.connect(lambda: self._redact_page_spin.setValue(
            min(self._redact_page_count, self._redact_page_spin.value() + 1)
        ))
        page_row.addWidget(prev_btn)
        page_row.addWidget(next_btn)
        page_row.addStretch()
        layout.addLayout(page_row)

        self._redact_page_view = PDFPageView(0)
        self._redact_page_view.set_annotate_mode(True, "highlight")
        self._redact_page_view.regionSelected.connect(self._redact_on_region)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)
        scroll.setWidget(self._redact_page_view)
        layout.addWidget(scroll)

        self._redact_list = QListWidget()
        self._redact_list.setMaximumHeight(100)
        apply_list_widget_style(self._redact_list)
        layout.addWidget(self._redact_list)

        rm_btn = PushButton("移除选中区域")
        rm_btn.clicked.connect(self._redact_remove_selected)
        layout.addWidget(rm_btn)

        self._redact_text = LineEdit()
        self._redact_text.setPlaceholderText("文字关键词（可选）")
        layout.addWidget(self._redact_text)

        out_row = QHBoxLayout()
        self._redact_out = LineEdit()
        self._redact_out.setPlaceholderText("输出 PDF 路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._redact_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "redacted.pdf", "PDF (*.pdf)")[0]
            or self._redact_out.text()
        ))
        out_row.addWidget(self._redact_out, 1)
        out_row.addWidget(b)
        layout.addLayout(out_row)

        run_btn = PrimaryPushButton(FluentIcon.DELETE, "应用涂黑")
        run_btn.clicked.connect(self._redact_apply)
        layout.addWidget(run_btn)

        self._redact_progress = TaskProgressCard("准备就绪")
        self._redact_progress.setVisible(False)
        layout.addWidget(self._redact_progress)
        layout.addStretch()
        return w

    def _redact_load(self, paths: list[str]) -> None:
        if not paths:
            return
        path = paths[0]
        try:
            info = PDFReaderUtil.get_info(path)
        except Exception as e:
            show_error(self, "无法打开", str(e))
            return
        self._redact_path = path
        self._redact_password = ""
        self._redact_page_count = info.page_count
        self._redact_regions.clear()
        self._redact_list.clear()
        self._redact_label.setText(f"{Path(path).name}  ·  {info.page_count} 页")
        self._redact_out.setText(str(
            Path(path).with_name(f"{Path(path).stem}_redacted.pdf")
        ))
        self._redact_page_spin.setRange(1, max(1, info.page_count))
        self._redact_page_spin.setValue(1)
        self._redact_render_page()

    def _redact_on_page_changed(self) -> None:
        self._redact_render_page()

    def _redact_render_page(self) -> None:
        if not self._redact_path:
            return
        page_index = self._redact_page_spin.value() - 1
        self._redact_page_view.page_index = page_index
        w = PDFPageRenderWorker(
            self._redact_path, page_index, zoom=1.0, password=self._redact_password
        )
        w.signals.finished.connect(self._redact_on_page_rendered)
        w.signals.error.connect(lambda m: show_error(self, "渲染失败", m))
        submit_worker(w)

    def _redact_on_page_rendered(self, result) -> None:
        png, pw, ph = result
        self._redact_page_view.set_page_pixmap(png, pw, ph)

    def _redact_on_region(
        self, page_index: int, x0: float, y0: float, x1: float, y1: float
    ) -> None:
        self._redact_regions.append(RedactRegion(page_index, (x0, y0, x1, y1)))
        self._redact_refresh_list()

    def _redact_refresh_list(self) -> None:
        self._redact_list.clear()
        for i, r in enumerate(self._redact_regions):
            x0, y0, x1, y1 = r.rect
            self._redact_list.addItem(QListWidgetItem(
                f"{i + 1}. 第 {r.page_index + 1} 页 "
                f"({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})"
            ))

    def _redact_remove_selected(self) -> None:
        row = self._redact_list.currentRow()
        if row < 0 or row >= len(self._redact_regions):
            show_warning(self, "请先选择要移除的区域")
            return
        self._redact_regions.pop(row)
        self._redact_refresh_list()

    def _redact_apply(self) -> None:
        if not self._redact_path:
            show_warning(self, "请先导入 PDF")
            return
        out = self._redact_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        patterns = [
            p.strip() for p in self._redact_text.text().split(",") if p.strip()
        ]
        if not self._redact_regions and not patterns:
            show_warning(self, "请框选涂黑区域或输入文字关键词")
            return
        self._redact_progress.setVisible(True)
        w = PDFRedactWorker(
            self._redact_path, out, self._redact_regions, patterns, self._redact_password
        )
        w.signals.progress.connect(self._redact_progress.update_progress)
        w.signals.finished.connect(lambda r: (
            self._redact_progress.set_finished(
                True,
                f"涂黑 {r.redacted_regions} 区域，文字 {r.redacted_text_blocks} 处",
            ),
            finish_output_task(self, "涂黑完成", r.path),
        ))
        w.signals.error.connect(lambda m: (
            self._redact_progress.set_finished(False, m),
            show_error(self, "涂黑失败", m),
        ))
        submit_worker(w)

    # ── 打字机 ──────────────────────────────

    def _build_typewriter_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放 PDF 文件")
        drop.filesDropped.connect(lambda ps: ps and self._load_type_pdf(ps[0]))
        layout.addWidget(drop)

        self._type_file_label = CaptionLabel("")
        self._type_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._type_file_label)

        form = QFormLayout()
        self._type_page = SpinBox()
        self._type_page.setRange(1, 9999)
        self._type_page.setValue(1)
        form.addRow("页码：", self._type_page)

        self._type_text = LineEdit()
        self._type_text.setPlaceholderText("要叠加的文字内容")
        form.addRow("文字：", self._type_text)

        self._type_size = SpinBox()
        self._type_size.setRange(6, 72)
        self._type_size.setValue(12)
        form.addRow("字号：", self._type_size)

        pos_row = QHBoxLayout()
        self._type_x = SpinBox()
        self._type_x.setRange(0, 2000)
        self._type_x.setValue(72)
        self._type_y = SpinBox()
        self._type_y.setRange(0, 2000)
        self._type_y.setValue(72)
        self._type_w = SpinBox()
        self._type_w.setRange(50, 2000)
        self._type_w.setValue(400)
        self._type_h = SpinBox()
        self._type_h.setRange(20, 2000)
        self._type_h.setValue(100)
        pos_row.addWidget(CaptionLabel("X"))
        pos_row.addWidget(self._type_x)
        pos_row.addWidget(CaptionLabel("Y"))
        pos_row.addWidget(self._type_y)
        pos_row.addWidget(CaptionLabel("宽"))
        pos_row.addWidget(self._type_w)
        pos_row.addWidget(CaptionLabel("高"))
        pos_row.addWidget(self._type_h)
        form.addRow("位置 (pt)：", pos_row)

        out_row = QHBoxLayout()
        self._type_out = LineEdit()
        self._type_out.setPlaceholderText("输出 PDF 路径")
        browse = PushButton("浏览")
        browse.clicked.connect(self._browse_type_out)
        out_row.addWidget(self._type_out, 1)
        out_row.addWidget(browse)
        form.addRow("输出：", out_row)
        layout.addLayout(form)

        hint = BodyLabel("在 PDF 页面上叠加新文字（打字机效果），不修改原有文字层。")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        self._type_progress = TaskProgressCard("准备就绪")
        self._type_progress.setVisible(False)
        layout.addWidget(self._type_progress)

        btn = PrimaryPushButton(FluentIcon.EDIT, "叠加文字")
        btn.clicked.connect(self._run_typewriter)
        layout.addWidget(btn)
        layout.addStretch()
        return widget

    def _load_type_pdf(self, path: str) -> None:
        try:
            info = PDFReaderUtil.get_info(path)
        except Exception as e:
            show_error(self, "无法打开 PDF", str(e))
            return
        self._type_path = path
        self._type_file_label.setText(f"{Path(path).name}  ·  {info.page_count} 页")
        self._type_page.setMaximum(info.page_count)
        out_dir = settings_mgr.resolve_output_dir(path)
        self._type_out.setText(str(out_dir / f"{Path(path).stem}_typed.pdf"))

    def _browse_type_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存 PDF", "typed.pdf", "PDF (*.pdf)")
        if path:
            self._type_out.setText(path)

    def _run_typewriter(self) -> None:
        if not self._type_path:
            show_warning(self, "请先导入 PDF")
            return
        text = self._type_text.text().strip()
        if not text:
            show_warning(self, "请输入要叠加的文字")
            return
        out = self._type_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        page_idx = self._type_page.value() - 1
        x, y = self._type_x.value(), self._type_y.value()
        w, h = self._type_w.value(), self._type_h.value()
        item = TextOverlayItem(
            page_index=page_idx,
            rect=(x, y, x + w, y + h),
            text=text,
            font_size=float(self._type_size.value()),
        )
        self._type_progress.setVisible(True)
        worker = PDFTextOverlayWorker(self._type_path, out, [item])
        worker.signals.finished.connect(lambda p: (
            self._type_progress.set_finished(True),
            finish_output_task(self, "文字已叠加", p),
        ))
        worker.signals.error.connect(lambda m: (
            self._type_progress.set_finished(False, m),
            show_error(self, "叠加失败", m),
        ))
        submit_worker(worker)

    # ── 文档信息 ──────────────────────────────

    def _build_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("pdf", "拖放 PDF 文件")
        drop.filesDropped.connect(lambda ps: ps and self._load_meta_pdf(ps[0]))
        layout.addWidget(drop)

        self._meta_file_label = CaptionLabel("")
        self._meta_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._meta_file_label)

        form = QFormLayout()
        self._meta_title = LineEdit()
        self._meta_author = LineEdit()
        self._meta_subject = LineEdit()
        self._meta_keywords = LineEdit()
        form.addRow("标题：", self._meta_title)
        form.addRow("作者：", self._meta_author)
        form.addRow("主题：", self._meta_subject)
        form.addRow("关键词：", self._meta_keywords)

        out_row = QHBoxLayout()
        self._meta_out = LineEdit()
        self._meta_out.setPlaceholderText("输出 PDF 路径")
        browse = PushButton("浏览")
        browse.clicked.connect(self._browse_meta_out)
        out_row.addWidget(self._meta_out, 1)
        out_row.addWidget(browse)
        form.addRow("输出：", out_row)
        layout.addLayout(form)

        self._meta_current = BodyLabel("")
        self._meta_current.setStyleSheet("color:#888;")
        layout.addWidget(self._meta_current)

        self._meta_progress = TaskProgressCard("准备就绪")
        self._meta_progress.setVisible(False)
        layout.addWidget(self._meta_progress)

        btn = PrimaryPushButton(FluentIcon.INFO, "更新元数据")
        btn.clicked.connect(self._run_metadata)
        layout.addWidget(btn)
        layout.addStretch()
        return widget

    def _load_meta_pdf(self, path: str) -> None:
        try:
            import fitz
            info = PDFReaderUtil.get_info(path)
            doc = fitz.open(path)
            meta = doc.metadata or {}
            doc.close()
        except Exception as e:
            show_error(self, "无法打开 PDF", str(e))
            return
        self._meta_path = path
        self._meta_file_label.setText(f"{Path(path).name}  ·  {info.page_count} 页")
        self._meta_title.setText(meta.get("title", "") or "")
        self._meta_author.setText(meta.get("author", "") or "")
        self._meta_subject.setText(meta.get("subject", "") or "")
        self._meta_keywords.setText(meta.get("keywords", "") or "")
        self._meta_current.setText(
            f"当前：标题={meta.get('title') or '—'}  "
            f"作者={meta.get('author') or '—'}"
        )
        out_dir = settings_mgr.resolve_output_dir(path)
        self._meta_out.setText(str(out_dir / f"{Path(path).stem}_meta.pdf"))

    def _browse_meta_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存 PDF", "meta.pdf", "PDF (*.pdf)")
        if path:
            self._meta_out.setText(path)

    def _run_metadata(self) -> None:
        if not self._meta_path:
            show_warning(self, "请先导入 PDF")
            return
        out = self._meta_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        self._meta_progress.setVisible(True)
        worker = PDFMetadataWorker(
            self._meta_path,
            out,
            title=self._meta_title.text().strip(),
            author=self._meta_author.text().strip(),
            subject=self._meta_subject.text().strip(),
            keywords=self._meta_keywords.text().strip(),
        )
        worker.signals.finished.connect(lambda p: (
            self._meta_progress.set_finished(True),
            finish_output_task(self, "元数据已更新", p),
        ))
        worker.signals.error.connect(lambda m: (
            self._meta_progress.set_finished(False, m),
            show_error(self, "更新失败", m),
        ))
        submit_worker(worker)
