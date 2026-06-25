"""
PDF Studio - 水印与页码页面
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTabWidget
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CheckBox,
    SpinBox, StrongBodyLabel, FluentIcon, LineEdit,
    DoubleSpinBox,
)
from app.widgets.combo_box import StudioComboBox
from app.widgets.common import DropZone, TaskProgressCard, show_success, show_error, show_warning, finish_output_task, wps_hint_label
from app.workers.base_worker import WatermarkWorker, BaseWorker, submit_worker
from core.pdf.processor import WatermarkOptions, PageNumberOptions, PDFPageNumberer


class WatermarkPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("watermarkPage")
        self._setup_ui()

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)
        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("水印 & 页码"))
        root.addWidget(wps_hint_label("watermark"))
        root.addWidget(CaptionLabel("为PDF添加文字水印或页码，支持透明度和位置自定义"))

        tabs = QTabWidget()
        tabs.addTab(self._build_watermark_tab(), "文字水印")
        tabs.addTab(self._build_image_watermark_tab(), "图片水印")
        tabs.addTab(self._build_page_number_tab(), "页码")
        root.addWidget(tabs)
        root.addStretch()

    # ── 水印 Tab ──────────────────────────────

    def _build_watermark_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放PDF文件")
        drop.filesDropped.connect(lambda p: self._set_wm_file(p))
        layout.addWidget(drop)
        self._wm_file_label = CaptionLabel("")
        self._wm_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._wm_file_label)
        self._wm_path: Optional[str] = None
        self._wm_page_count = 0

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        c_l.addWidget(CaptionLabel("水印文字："))
        self._wm_text = LineEdit()
        self._wm_text.setPlaceholderText("请输入水印文字，例：机密文件")
        c_l.addWidget(self._wm_text)

        size_row = QHBoxLayout()
        size_row.addWidget(CaptionLabel("字体大小："))
        self._wm_size = SpinBox()
        self._wm_size.setRange(12, 200)
        self._wm_size.setValue(48)
        size_row.addWidget(self._wm_size)
        size_row.addStretch()
        c_l.addLayout(size_row)

        rot_row = QHBoxLayout()
        rot_row.addWidget(CaptionLabel("旋转角度："))
        self._wm_rot = SpinBox()
        self._wm_rot.setRange(-180, 180)
        self._wm_rot.setValue(45)
        rot_row.addWidget(self._wm_rot)
        rot_row.addStretch()
        c_l.addLayout(rot_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(CaptionLabel("透明度（0-100）："))
        self._wm_opacity = SpinBox()
        self._wm_opacity.setRange(0, 100)
        self._wm_opacity.setValue(30)
        opacity_row.addWidget(self._wm_opacity)
        opacity_row.addStretch()
        c_l.addLayout(opacity_row)

        pos_row = QHBoxLayout()
        pos_row.addWidget(CaptionLabel("排列方式："))
        self._wm_pos = StudioComboBox()
        self._wm_pos.addItems(["居中", "平铺"])
        pos_row.addWidget(self._wm_pos)
        pos_row.addStretch()
        c_l.addLayout(pos_row)

        c_l.addWidget(CaptionLabel("应用页码（留空=全部页，例：1-3,5）："))
        self._wm_pages = LineEdit()
        self._wm_pages.setPlaceholderText("留空表示全部页面")
        c_l.addWidget(self._wm_pages)

        out_row = QHBoxLayout()
        self._wm_out = LineEdit()
        self._wm_out.setPlaceholderText("输出路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._wm_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "watermarked.pdf", "PDF (*.pdf)")[0]
            or self._wm_out.text()
        ))
        out_row.addWidget(self._wm_out, 1)
        out_row.addWidget(b)
        c_l.addLayout(out_row)
        layout.addWidget(card)

        btn = PrimaryPushButton(FluentIcon.EDIT, "添加水印")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._apply_watermark)
        layout.addWidget(btn)

        self._wm_progress = TaskProgressCard("准备就绪")
        self._wm_progress.setVisible(False)
        layout.addWidget(self._wm_progress)
        layout.addStretch()
        return w

    def _build_image_watermark_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放PDF文件")
        drop.filesDropped.connect(lambda p: self._set_img_wm_file(p))
        layout.addWidget(drop)
        self._img_wm_file_label = CaptionLabel("")
        self._img_wm_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._img_wm_file_label)
        self._img_wm_path: Optional[str] = None
        self._img_wm_page_count = 0

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        img_row = QHBoxLayout()
        self._img_wm_image = LineEdit()
        self._img_wm_image.setPlaceholderText("水印图片路径（PNG/JPG，建议透明背景）")
        img_browse = PushButton("浏览")
        img_browse.clicked.connect(self._browse_wm_image)
        img_row.addWidget(self._img_wm_image, 1)
        img_row.addWidget(img_browse)
        c_l.addLayout(img_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(CaptionLabel("图片缩放（%）："))
        self._img_wm_scale = SpinBox()
        self._img_wm_scale.setRange(10, 300)
        self._img_wm_scale.setValue(100)
        scale_row.addWidget(self._img_wm_scale)
        scale_row.addStretch()
        c_l.addLayout(scale_row)

        rot_row = QHBoxLayout()
        rot_row.addWidget(CaptionLabel("旋转角度："))
        self._img_wm_rot = SpinBox()
        self._img_wm_rot.setRange(-180, 180)
        self._img_wm_rot.setValue(0)
        rot_row.addWidget(self._img_wm_rot)
        rot_row.addStretch()
        c_l.addLayout(rot_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(CaptionLabel("透明度（0-100）："))
        self._img_wm_opacity = SpinBox()
        self._img_wm_opacity.setRange(0, 100)
        self._img_wm_opacity.setValue(30)
        opacity_row.addWidget(self._img_wm_opacity)
        opacity_row.addStretch()
        c_l.addLayout(opacity_row)

        pos_row = QHBoxLayout()
        pos_row.addWidget(CaptionLabel("排列方式："))
        self._img_wm_pos = StudioComboBox()
        self._img_wm_pos.addItems(["居中", "平铺"])
        pos_row.addWidget(self._img_wm_pos)
        pos_row.addStretch()
        c_l.addLayout(pos_row)

        c_l.addWidget(CaptionLabel("应用页码（留空=全部页）："))
        self._img_wm_pages = LineEdit()
        c_l.addWidget(self._img_wm_pages)

        out_row = QHBoxLayout()
        self._img_wm_out = LineEdit()
        self._img_wm_out.setPlaceholderText("输出路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._img_wm_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "image_watermarked.pdf", "PDF (*.pdf)")[0]
            or self._img_wm_out.text()
        ))
        out_row.addWidget(self._img_wm_out, 1)
        out_row.addWidget(b)
        c_l.addLayout(out_row)
        layout.addWidget(card)

        btn = PrimaryPushButton(FluentIcon.PHOTO, "添加图片水印")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._apply_image_watermark)
        layout.addWidget(btn)

        self._img_wm_progress = TaskProgressCard("准备就绪")
        self._img_wm_progress.setVisible(False)
        layout.addWidget(self._img_wm_progress)
        layout.addStretch()
        return w

    # ── 页码 Tab ──────────────────────────────

    def _build_page_number_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放PDF文件")
        drop.filesDropped.connect(lambda p: self._set_pn_file(p))
        layout.addWidget(drop)
        self._pn_file_label = CaptionLabel("")
        self._pn_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._pn_file_label)
        self._pn_path: Optional[str] = None

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        pos_row = QHBoxLayout()
        pos_row.addWidget(CaptionLabel("页码位置："))
        self._pn_pos = StudioComboBox()
        self._pn_pos.addItems([
            "底部居中", "底部右侧", "底部左侧",
            "顶部居中", "顶部右侧", "顶部左侧",
        ])
        pos_row.addWidget(self._pn_pos)
        pos_row.addStretch()
        c_l.addLayout(pos_row)

        start_row = QHBoxLayout()
        start_row.addWidget(CaptionLabel("起始页码："))
        self._pn_start = SpinBox()
        self._pn_start.setRange(1, 9999)
        self._pn_start.setValue(1)
        start_row.addWidget(self._pn_start)
        start_row.addStretch()
        c_l.addLayout(start_row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(CaptionLabel("格式（{n}=页码 {total}=总页）："))
        self._pn_fmt = LineEdit()
        self._pn_fmt.setText("{n}")
        fmt_row.addWidget(self._pn_fmt)
        c_l.addLayout(fmt_row)

        self._pn_skip_first = CheckBox("首页不显示页码")
        c_l.addWidget(self._pn_skip_first)

        size_row = QHBoxLayout()
        size_row.addWidget(CaptionLabel("字体大小："))
        self._pn_size = SpinBox()
        self._pn_size.setRange(8, 48)
        self._pn_size.setValue(12)
        size_row.addWidget(self._pn_size)
        size_row.addStretch()
        c_l.addLayout(size_row)

        out_row = QHBoxLayout()
        self._pn_out = LineEdit()
        self._pn_out.setPlaceholderText("输出路径")
        b = PushButton("浏览")
        b.clicked.connect(lambda: self._pn_out.setText(
            QFileDialog.getSaveFileName(self, "保存", "numbered.pdf", "PDF (*.pdf)")[0]
            or self._pn_out.text()
        ))
        out_row.addWidget(self._pn_out, 1)
        out_row.addWidget(b)
        c_l.addLayout(out_row)
        layout.addWidget(card)

        btn = PrimaryPushButton(FluentIcon.EDIT, "添加页码")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._apply_page_numbers)
        layout.addWidget(btn)

        self._pn_progress = TaskProgressCard("准备就绪")
        self._pn_progress.setVisible(False)
        layout.addWidget(self._pn_progress)
        layout.addStretch()
        return w

    def _set_wm_file(self, paths):
        if paths:
            self._wm_path = paths[0]
            self._wm_file_label.setText(Path(paths[0]).name)
            self._wm_page_count = self._load_page_count(paths[0])

    def _set_img_wm_file(self, paths):
        if paths:
            self._img_wm_path = paths[0]
            self._img_wm_file_label.setText(Path(paths[0]).name)
            self._img_wm_page_count = self._load_page_count(paths[0])

    def _load_page_count(self, path: str) -> int:
        try:
            from core.pdf.processor import PDFReader
            return PDFReader.get_info(path).page_count
        except Exception:
            return 0

    def _browse_wm_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择水印图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if path:
            self._img_wm_image.setText(path)

    def _parse_pages(self, spec: str, page_count: int) -> Optional[list[int]]:
        spec = spec.strip()
        if not spec:
            return None
        from core.pdf.processor import PDFReader
        pages = PDFReader.parse_page_range(spec, page_count)
        if not pages:
            raise ValueError("页码范围无效")
        return pages

    def _apply_watermark(self):
        if not self._wm_path:
            show_warning(self, "请先导入PDF")
            return
        text = self._wm_text.text().strip()
        if not text:
            show_warning(self, "请输入水印文字")
            return
        out = self._wm_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        try:
            pages = self._parse_pages(self._wm_pages.text(), self._wm_page_count)
        except ValueError as e:
            show_warning(self, str(e))
            return

        options = WatermarkOptions(
            text=text,
            font_size=self._wm_size.value(),
            rotation=float(self._wm_rot.value()),
            opacity=self._wm_opacity.value() / 100.0,
            position="tile" if self._wm_pos.currentText() == "平铺" else "center",
            pages=pages,
        )
        self._run_watermark(self._wm_path, out, options, self._wm_progress)

    def _apply_image_watermark(self):
        if not self._img_wm_path:
            show_warning(self, "请先导入PDF")
            return
        img = self._img_wm_image.text().strip()
        if not img or not Path(img).is_file():
            show_warning(self, "请选择有效的水印图片")
            return
        out = self._img_wm_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return
        try:
            pages = self._parse_pages(self._img_wm_pages.text(), self._img_wm_page_count)
        except ValueError as e:
            show_warning(self, str(e))
            return

        options = WatermarkOptions(
            image_path=Path(img),
            image_scale=self._img_wm_scale.value() / 100.0,
            rotation=float(self._img_wm_rot.value()),
            opacity=self._img_wm_opacity.value() / 100.0,
            position="tile" if self._img_wm_pos.currentText() == "平铺" else "center",
            pages=pages,
        )
        self._run_watermark(self._img_wm_path, out, options, self._img_wm_progress)

    def _run_watermark(self, src: str, out: str, options: WatermarkOptions, progress_card):
        progress_card.setVisible(True)
        w = WatermarkWorker(src, out, options)
        w.signals.progress.connect(progress_card.update_progress)
        w.signals.finished.connect(lambda p: (
            progress_card.set_finished(True),
            finish_output_task(self, "水印添加完成", p),
        ))
        w.signals.error.connect(lambda msg: (
            progress_card.set_finished(False, msg),
            show_error(self, "添加失败", msg),
        ))
        submit_worker(w)

    def _set_pn_file(self, paths):
        if paths:
            self._pn_path = paths[0]
            self._pn_file_label.setText(Path(paths[0]).name)

    def _apply_page_numbers(self):
        if not self._pn_path:
            show_warning(self, "请先导入PDF")
            return
        out = self._pn_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        pos_map = {
            "底部居中": "bottom_center", "底部右侧": "bottom_right", "底部左侧": "bottom_left",
            "顶部居中": "top_center", "顶部右侧": "top_right", "顶部左侧": "top_left",
        }
        options = PageNumberOptions(
            position=pos_map.get(self._pn_pos.currentText(), "bottom_center"),
            start_number=self._pn_start.value(),
            skip_first=self._pn_skip_first.isChecked(),
            font_size=self._pn_size.value(),
            format_str=self._pn_fmt.text() or "{n}",
        )
        src = self._pn_path

        self._pn_progress.setVisible(True)

        class PNWorker(BaseWorker):
            def __init__(self_, src, out, opts):
                super().__init__()
                self_.src = src; self_.out = out; self_.opts = opts
            def run_task(self_):
                return PDFPageNumberer().add_page_numbers(
                    self_.src, self_.out, self_.opts, self_.emit_progress
                )

        w = PNWorker(src, out, options)
        w.signals.progress.connect(self._pn_progress.update_progress)
        w.signals.finished.connect(lambda p: (
            self._pn_progress.set_finished(True),
            finish_output_task(self, "页码添加完成", p),
        ))
        w.signals.error.connect(lambda msg: (
            self._pn_progress.set_finished(False, msg),
            show_error(self, "添加失败", msg),
        ))
        submit_worker(w)
