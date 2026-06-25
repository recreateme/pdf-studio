"""
PDF Studio - 图片工具页面
PDF↔图片互转，图像增强
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTabWidget,
    QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CheckBox,
    SpinBox, StrongBodyLabel, FluentIcon, LineEdit,
    SegmentedWidget,
)
from app.widgets.image_merge_list import ImageMergeList
from app.widgets.list_styles import apply_list_widget_style
from app.widgets.combo_box import StudioComboBox
from app.widgets.common import (
    DropZone, ThumbnailPanel, TaskProgressCard,
    show_success, show_error, show_warning, show_info, wps_hint_label, finish_output_task,
)
from app.workers.base_worker import (
    PDFToImageWorker, ImageToPDFWorker, ThumbnailWorker,
    PDFExtractTextWorker, PDFExtractImagesWorker, ImageEnhanceWorker,
    PDFLongImageWorker, ImageMergeWorker, ImageCompressWorker, submit_worker,
)
from app.config.settings import settings_mgr
from app.config.constants import IMAGE_EXPORT_FORMATS, get_default_dpi, get_thumbnail_width
from app.utils.helpers import collect_files
from core.image.converter import PDFToImageOptions, ImageToPDFOptions, ImageEnhanceOptions
from core.image.merger import ImageMergeOptions
from core.image.compressor import ImageCompressOptions


class ImagePage(QWidget):
    """图片工具页面（PDF↔图片）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imagePage")
        self._pdf_path: Optional[str] = None
        self._pdf_info = None
        self._image_paths: list[str] = []
        self._extract_path: Optional[str] = None
        self._extract_page_count = 0
        self._scan_paths: list[str] = []
        self._scan_last_outputs: list[str] = []
        self._compress_paths: list[str] = []
        self._setup_ui()
        self._apply_setting_defaults()

    def _apply_setting_defaults(self) -> None:
        self._p2i_dpi.setValue(get_default_dpi())
        if settings_mgr.pdf.default_output_dir:
            self._p2i_out_edit.setText(settings_mgr.pdf.default_output_dir)
            self._merge_out.setText(settings_mgr.pdf.default_output_dir)
            self._compress_out.setText(settings_mgr.pdf.default_output_dir)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)
        root.addWidget(TitleLabel("图片工具"))
        root.addWidget(wps_hint_label("image"))
        root.addWidget(CaptionLabel("PDF 转图片 · 图片合并 · 图片压缩 · 图片转 PDF · 内容提取 · 扫描增强"))

        self._image_tabs = QTabWidget()
        self._image_tabs.addTab(self._build_pdf_to_image_tab(), "PDF → 图片")
        self._image_tabs.addTab(self._build_image_merge_tab(), "图片合并")
        self._image_tabs.addTab(self._build_image_compress_tab(), "图片压缩")
        self._image_tabs.addTab(self._build_image_to_pdf_tab(), "图片 → PDF")
        self._image_tabs.addTab(self._build_extract_tab(), "内容提取")
        self._image_tabs.addTab(self._build_scan_tab(), "扫描增强")
        root.addWidget(self._image_tabs, 1)

    # ── PDF→图片 Tab ──────────────────────────

    def _build_pdf_to_image_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 左：控制
        left = QWidget()
        left.setFixedWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        drop = DropZone("pdf", "拖放PDF文件到此处")
        drop.filesDropped.connect(self._p2i_load_pdf)
        left_layout.addWidget(drop)

        self._p2i_file_label = CaptionLabel("")
        self._p2i_file_label.setStyleSheet("color:#888;")
        left_layout.addWidget(self._p2i_file_label)

        settings_card = CardWidget()
        s_layout = QVBoxLayout(settings_card)
        s_layout.setContentsMargins(14, 12, 14, 12)
        s_layout.setSpacing(8)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(CaptionLabel("输出格式："))
        self._p2i_fmt = StudioComboBox()
        self._p2i_fmt.addItems(IMAGE_EXPORT_FORMATS)
        fmt_row.addWidget(self._p2i_fmt)
        fmt_row.addStretch()
        s_layout.addLayout(fmt_row)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(CaptionLabel("DPI："))
        self._p2i_dpi = SpinBox()
        self._p2i_dpi.setRange(72, 600)
        self._p2i_dpi.setValue(150)
        dpi_row.addWidget(self._p2i_dpi)
        dpi_row.addStretch()
        s_layout.addLayout(dpi_row)

        self._p2i_sharpen = CheckBox("锐化")
        self._p2i_gray = CheckBox("灰度化")
        self._p2i_denoise = CheckBox("去噪")
        self._p2i_long = CheckBox("合并为长图（纵向拼接）")
        s_layout.addWidget(self._p2i_sharpen)
        s_layout.addWidget(self._p2i_gray)
        s_layout.addWidget(self._p2i_denoise)
        s_layout.addWidget(self._p2i_long)

        out_row = QHBoxLayout()
        self._p2i_out_edit = LineEdit()
        self._p2i_out_edit.setPlaceholderText("输出目录")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._p2i_out_edit.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._p2i_out_edit.text()
        ))
        out_row.addWidget(self._p2i_out_edit, 1)
        out_row.addWidget(browse)
        s_layout.addLayout(out_row)

        left_layout.addWidget(settings_card)

        self._p2i_btn = PrimaryPushButton(FluentIcon.PHOTO, "开始转换")
        self._p2i_btn.setFixedHeight(38)
        self._p2i_btn.clicked.connect(self._start_p2i)
        left_layout.addWidget(self._p2i_btn)

        self._p2i_progress = TaskProgressCard("准备就绪")
        self._p2i_progress.setVisible(False)
        left_layout.addWidget(self._p2i_progress)
        left_layout.addStretch()

        # 右：缩略图
        self._p2i_thumbs = ThumbnailPanel()
        layout.addWidget(left)
        layout.addWidget(self._p2i_thumbs, 1)
        return widget

    def _p2i_load_pdf(self, paths):
        if not paths:
            return
        path = paths[0]
        self._pdf_path = path
        try:
            from core.pdf.processor import PDFReader as R
            self._pdf_info = R.get_info(path)
            self._p2i_file_label.setText(f"{Path(path).name}  ·  {self._pdf_info.page_count} 页")
            self._p2i_thumbs.clear()
            for i in range(self._pdf_info.page_count):
                self._p2i_thumbs.add_page(i)
            w = ThumbnailWorker(
                path,
                list(range(self._pdf_info.page_count)),
                width=get_thumbnail_width(),
            )
            w.signals.finished.connect(lambda res: [
                self._p2i_thumbs.get_card(i) and self._p2i_thumbs.get_card(i).set_thumbnail(d)
                for i, d in res
            ])
            submit_worker(w)
            settings_mgr.add_recent_file(path)
        except Exception as e:
            show_error(self, "加载失败", str(e))

    def _start_p2i(self):
        if not self._pdf_path:
            show_warning(self, "请先导入PDF")
            return
        out_dir = self._p2i_out_edit.text().strip()
        if not out_dir:
            out_dir = str(settings_mgr.resolve_output_dir(self._pdf_path))
            self._p2i_out_edit.setText(out_dir)

        selected = self._p2i_thumbs.get_selected()
        options = PDFToImageOptions(
            output_dir=Path(out_dir),
            format=self._p2i_fmt.currentText(),
            dpi=self._p2i_dpi.value(),
            pages=selected if selected else None,
            sharpen=self._p2i_sharpen.isChecked(),
            grayscale=self._p2i_gray.isChecked(),
            denoise=self._p2i_denoise.isChecked(),
        )
        self._p2i_btn.setEnabled(False)
        self._p2i_progress.setVisible(True)

        if self._p2i_long.isChecked():
            fmt = self._p2i_fmt.currentText().upper()
            ext = ".jpg" if fmt in ("JPEG", "JPG") else f".{fmt.lower()}"
            out_path = Path(out_dir) / f"{Path(self._pdf_path).stem}_long{ext}"
            w = PDFLongImageWorker(self._pdf_path, str(out_path), options)
            w.signals.progress.connect(self._p2i_progress.update_progress)
            w.signals.finished.connect(lambda p: (
                self._p2i_btn.setEnabled(True),
                self._p2i_progress.set_finished(True, "长图已生成"),
                finish_output_task(self, "长图导出完成", p),
            ))
        else:
            w = PDFToImageWorker(self._pdf_path, options)
            w.signals.progress.connect(self._p2i_progress.update_progress)
            w.signals.finished.connect(lambda res: (
                self._p2i_btn.setEnabled(True),
                self._p2i_progress.set_finished(True, f"共 {len(res)} 张图片"),
                finish_output_task(self, f"已导出 {len(res)} 张图片", res[0] if res else out_dir),
            ))

        w.signals.error.connect(lambda msg: (
            self._p2i_btn.setEnabled(True),
            self._p2i_progress.set_finished(False, msg),
            show_error(self, "转换失败", msg),
        ))
        submit_worker(w)

    # ── 图片合并 Tab ──────────────────────────

    def _build_image_merge_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(392)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(10)

        drop = DropZone("image", "拖放图片到此处（可多选）")
        drop.filesDropped.connect(self._merge_add_images)
        left_l.addWidget(drop)

        btn_row = QHBoxLayout()
        add_btn = PushButton(FluentIcon.FOLDER, "添加文件夹")
        add_btn.clicked.connect(self._merge_add_folder)
        file_btn = PushButton("添加图片")
        file_btn.clicked.connect(self._merge_browse_files)
        left_l.addLayout(btn_row)
        btn_row.addWidget(file_btn)
        btn_row.addWidget(add_btn)

        s_card = CardWidget()
        s_l = QVBoxLayout(s_card)
        s_l.setContentsMargins(14, 12, 14, 12)
        s_l.setSpacing(10)

        s_l.addWidget(CaptionLabel("合并方式："))
        self._merge_mode = SegmentedWidget()
        self._merge_mode.addItem("vertical", "纵向长图")
        self._merge_mode.addItem("horizontal", "横向长图")
        self._merge_mode.addItem("grid", "网格拼图")
        self._merge_mode.setCurrentItem("vertical")
        self._merge_mode.currentItemChanged.connect(self._on_merge_mode_changed)
        s_l.addWidget(self._merge_mode)

        self._merge_grid_panel = QWidget()
        grid_l = QVBoxLayout(self._merge_grid_panel)
        grid_l.setContentsMargins(0, 0, 0, 0)
        grid_l.setSpacing(6)

        rc_row = QHBoxLayout()
        rc_row.setSpacing(8)
        rc_row.addWidget(CaptionLabel("行数："))
        self._merge_rows = SpinBox()
        self._merge_rows.setRange(1, 10)
        self._merge_rows.setValue(3)
        self._merge_rows.setMinimumWidth(72)
        rc_row.addWidget(self._merge_rows)
        rc_row.addSpacing(12)
        rc_row.addWidget(CaptionLabel("列数："))
        self._merge_cols = SpinBox()
        self._merge_cols.setRange(1, 10)
        self._merge_cols.setValue(3)
        self._merge_cols.setMinimumWidth(72)
        rc_row.addWidget(self._merge_cols)
        rc_row.addStretch()
        grid_l.addLayout(rc_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_row.addWidget(CaptionLabel("预设："))
        for label, r, c in [("2×2", 2, 2), ("3×3", 3, 3), ("2×4", 2, 4), ("1×3", 1, 3)]:
            btn = PushButton(label)
            btn.setFixedWidth(44)
            btn.clicked.connect(lambda _=False, rr=r, cc=c: self._merge_apply_grid_preset(rr, cc))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        grid_l.addLayout(preset_row)

        page_suffix_row = QHBoxLayout()
        page_suffix_row.addWidget(CaptionLabel("多页后缀："))
        self._merge_page_suffix = LineEdit()
        self._merge_page_suffix.setPlaceholderText("_{page:03d}")
        self._merge_page_suffix.setText("_{page:03d}")
        self._merge_page_suffix.setToolTip("网格多页输出时追加到文件名，{page} 为页码（从 1 起）")
        page_suffix_row.addWidget(self._merge_page_suffix, 1)
        grid_l.addLayout(page_suffix_row)
        s_l.addWidget(self._merge_grid_panel)
        self._merge_grid_panel.setVisible(False)

        self._merge_fixed_panel = QWidget()
        fixed_l = QVBoxLayout(self._merge_fixed_panel)
        fixed_l.setContentsMargins(0, 0, 0, 0)
        fixed_l.setSpacing(6)

        self._merge_fixed_width_row = QWidget()
        width_row = QHBoxLayout(self._merge_fixed_width_row)
        width_row.setContentsMargins(0, 0, 0, 0)
        self._merge_fixed_width_cb = CheckBox("固定画布宽度")
        self._merge_fixed_width_cb.setToolTip("纵向长图：统一缩放到指定宽度后拼接")
        self._merge_fixed_width = SpinBox()
        self._merge_fixed_width.setRange(100, 10000)
        self._merge_fixed_width.setValue(1080)
        self._merge_fixed_width.setMinimumWidth(88)
        self._merge_fixed_width.setEnabled(False)
        self._merge_fixed_width_cb.toggled.connect(self._merge_fixed_width.setEnabled)
        width_row.addWidget(self._merge_fixed_width_cb)
        width_row.addWidget(self._merge_fixed_width)
        width_row.addStretch()
        fixed_l.addWidget(self._merge_fixed_width_row)

        self._merge_fixed_height_row = QWidget()
        height_row = QHBoxLayout(self._merge_fixed_height_row)
        height_row.setContentsMargins(0, 0, 0, 0)
        self._merge_fixed_height_cb = CheckBox("固定画布高度")
        self._merge_fixed_height_cb.setToolTip("横向长图：统一缩放到指定高度后拼接")
        self._merge_fixed_height = SpinBox()
        self._merge_fixed_height.setRange(100, 10000)
        self._merge_fixed_height.setValue(1080)
        self._merge_fixed_height.setMinimumWidth(88)
        self._merge_fixed_height.setEnabled(False)
        self._merge_fixed_height_cb.toggled.connect(self._merge_fixed_height.setEnabled)
        height_row.addWidget(self._merge_fixed_height_cb)
        height_row.addWidget(self._merge_fixed_height)
        height_row.addStretch()
        fixed_l.addWidget(self._merge_fixed_height_row)
        s_l.addWidget(self._merge_fixed_panel)

        gap_row = QHBoxLayout()
        gap_row.setSpacing(8)
        gap_row.addWidget(CaptionLabel("外边距："))
        self._merge_margin = SpinBox()
        self._merge_margin.setRange(0, 200)
        self._merge_margin.setValue(0)
        self._merge_margin.setMinimumWidth(72)
        gap_row.addWidget(self._merge_margin)
        gap_row.addSpacing(12)
        gap_row.addWidget(CaptionLabel("间距："))
        self._merge_spacing = SpinBox()
        self._merge_spacing.setRange(0, 100)
        self._merge_spacing.setValue(0)
        self._merge_spacing.setMinimumWidth(72)
        gap_row.addWidget(self._merge_spacing)
        gap_row.addStretch()
        s_l.addLayout(gap_row)

        self._merge_center = CheckBox("窄图居中（长图模式）")
        self._merge_center.setChecked(True)
        s_l.addWidget(self._merge_center)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(8)
        fmt_row.addWidget(CaptionLabel("输出格式："))
        self._merge_fmt = StudioComboBox()
        self._merge_fmt.addItems(["PNG", "JPEG", "WEBP"])
        self._merge_fmt.setMinimumWidth(120)
        fmt_row.addWidget(self._merge_fmt, 1)
        s_l.addLayout(fmt_row)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        quality_row.addWidget(CaptionLabel("输出质量："))
        self._merge_quality = SpinBox()
        self._merge_quality.setRange(60, 100)
        self._merge_quality.setValue(90)
        self._merge_quality.setMinimumWidth(72)
        quality_row.addWidget(self._merge_quality)
        self._merge_quality_hint = CaptionLabel("（仅 JPEG / WebP 有损时生效）")
        quality_row.addWidget(self._merge_quality_hint, 1)
        s_l.addLayout(quality_row)

        self._merge_webp_lossless = CheckBox("WebP 无损")
        self._merge_webp_lossless.setVisible(False)
        s_l.addWidget(self._merge_webp_lossless)
        self._merge_fmt.currentTextChanged.connect(self._on_merge_fmt_changed)
        self._merge_webp_lossless.toggled.connect(
            lambda _: self._on_merge_fmt_changed(self._merge_fmt.currentText())
        )

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(CaptionLabel("文件名："))
        self._merge_stem = LineEdit()
        self._merge_stem.setPlaceholderText("合并")
        self._merge_stem.setText("合并")
        name_row.addWidget(self._merge_stem, 1)
        s_l.addLayout(name_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self._merge_out = LineEdit()
        self._merge_out.setPlaceholderText("输出目录")
        browse = PushButton("浏览")
        browse.setFixedWidth(64)
        browse.clicked.connect(lambda: self._merge_out.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._merge_out.text()
        ))
        out_row.addWidget(self._merge_out, 1)
        out_row.addWidget(browse)
        s_l.addLayout(out_row)

        left_l.addWidget(s_card)

        self._merge_btn = PrimaryPushButton(FluentIcon.PHOTO, "开始合并")
        self._merge_btn.setFixedHeight(38)
        self._merge_btn.clicked.connect(self._start_merge)
        left_l.addWidget(self._merge_btn)

        self._merge_progress = TaskProgressCard("准备就绪")
        self._merge_progress.setVisible(False)
        left_l.addWidget(self._merge_progress)
        left_l.addStretch()

        self._merge_list = ImageMergeList()
        self._on_merge_mode_changed("vertical")
        self._on_merge_fmt_changed(self._merge_fmt.currentText())

        layout.addWidget(left)
        layout.addWidget(self._merge_list, 1)
        return widget

    def _on_merge_fmt_changed(self, fmt: str) -> None:
        fmt_u = fmt.upper()
        is_webp = fmt_u == "WEBP"
        self._merge_webp_lossless.setVisible(is_webp)
        if fmt_u == "PNG":
            self._merge_quality_hint.setText("（PNG 无损，此项不影响输出）")
        elif is_webp and self._merge_webp_lossless.isChecked():
            self._merge_quality_hint.setText("（WebP 无损已启用，此项不影响输出）")
        else:
            self._merge_quality_hint.setText("（JPEG / WebP 有损压缩时使用）")

    def _merge_build_options(self, out_dir: str | None = None) -> ImageMergeOptions:
        mode = self._merge_mode.currentRouteKey() or "vertical"
        fixed_w = self._merge_fixed_width.value() if self._merge_fixed_width_cb.isChecked() else 0
        fixed_h = self._merge_fixed_height.value() if self._merge_fixed_height_cb.isChecked() else 0
        directory = Path(out_dir) if out_dir else Path(".")
        return ImageMergeOptions(
            output_dir=directory,
            output_stem=self._merge_stem.text().strip() or "合并",
            mode=mode,
            format=self._merge_fmt.currentText(),
            jpeg_quality=self._merge_quality.value(),
            margin=self._merge_margin.value(),
            spacing=self._merge_spacing.value(),
            grid_rows=self._merge_rows.value(),
            grid_cols=self._merge_cols.value(),
            align_center=self._merge_center.isChecked(),
            fixed_canvas_width=fixed_w if mode == "vertical" else 0,
            fixed_canvas_height=fixed_h if mode == "horizontal" else 0,
            page_suffix_template=self._merge_page_suffix.text().strip() or "_{page:03d}",
            webp_lossless=self._merge_webp_lossless.isChecked(),
        )

    def _on_merge_mode_changed(self, key: str) -> None:
        is_grid = key == "grid"
        is_vertical = key == "vertical"
        is_horizontal = key == "horizontal"
        self._merge_grid_panel.setVisible(is_grid)
        self._merge_fixed_panel.setVisible(is_vertical or is_horizontal)
        self._merge_fixed_width_row.setVisible(is_vertical)
        self._merge_fixed_height_row.setVisible(is_horizontal)
        is_long = key in ("vertical", "horizontal")
        self._merge_center.setVisible(is_long)
        if is_grid:
            self._merge_margin.setValue(20)
            self._merge_spacing.setValue(8)
        else:
            self._merge_margin.setValue(0)
            self._merge_spacing.setValue(0)

    def _merge_apply_grid_preset(self, rows: int, cols: int) -> None:
        self._merge_rows.setValue(rows)
        self._merge_cols.setValue(cols)

    def _merge_filter_paths(self, paths: list[str]) -> list[str]:
        from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
        return [p for p in paths if Path(p).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS]

    def _merge_add_images(self, paths: list[str]) -> None:
        valid = self._merge_filter_paths(paths)
        skipped = len(paths) - len(valid)
        added = self._merge_list.add_files(valid)
        if skipped:
            show_warning(self, "部分文件已跳过", f"已跳过 {skipped} 个非图片文件")
        if added == 0 and valid:
            show_info(self, "提示", "所选图片已在列表中")

    def _merge_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
            imgs = [str(p) for p in collect_files(folder, SUPPORTED_IMAGE_EXTENSIONS)]
            self._merge_add_images(imgs)

    def _merge_browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.gif);;所有文件 (*.*)",
        )
        if paths:
            self._merge_add_images(paths)

    def _start_merge(self) -> None:
        paths = self._merge_list.get_paths()
        if not paths:
            show_warning(self, "请先添加图片")
            return
        if len(paths) < 2 and self._merge_mode.currentRouteKey() != "grid":
            show_warning(self, "提示", "长图合并建议至少 2 张图片")

        out_dir = self._merge_out.text().strip()
        if not out_dir:
            out_dir = str(settings_mgr.resolve_output_dir(paths[0]))
            self._merge_out.setText(out_dir)

        stem = self._merge_stem.text().strip() or "合并"
        options = self._merge_build_options(out_dir)
        options.output_stem = stem

        self._merge_btn.setEnabled(False)
        self._merge_progress.setVisible(True)
        w = ImageMergeWorker(paths, options)
        w.signals.progress.connect(self._merge_progress.update_progress)
        w.signals.finished.connect(lambda outputs: (
            self._merge_btn.setEnabled(True),
            self._merge_progress.set_finished(True, f"共 {len(outputs)} 个文件"),
            finish_output_task(
                self,
                f"合并完成（{len(outputs)} 个文件）",
                outputs[0] if outputs else out_dir,
            ),
        ))
        w.signals.error.connect(lambda msg: (
            self._merge_btn.setEnabled(True),
            self._merge_progress.set_finished(False, msg),
            show_error(self, "合并失败", msg),
        ))
        submit_worker(w)

    # ── 图片压缩 Tab ──────────────────────────

    def _build_image_compress_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(392)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(10)

        drop = DropZone("image", "拖放图片（可多选，支持批量压缩）")
        drop.filesDropped.connect(self._compress_add_files)
        left_l.addWidget(drop)

        btn_row = QHBoxLayout()
        add_btn = PushButton("添加图片")
        add_btn.clicked.connect(self._compress_browse)
        folder_btn = PushButton(FluentIcon.FOLDER, "添加文件夹")
        folder_btn.clicked.connect(self._compress_add_folder)
        clear_btn = PushButton("清空")
        clear_btn.clicked.connect(self._compress_clear)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(folder_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        left_l.addLayout(btn_row)

        s_card = CardWidget()
        s_l = QVBoxLayout(s_card)
        s_l.setContentsMargins(14, 12, 14, 12)
        s_l.setSpacing(10)

        s_l.addWidget(CaptionLabel("压缩方式："))
        self._compress_mode = SegmentedWidget()
        self._compress_mode.addItem("target_size", "目标大小")
        self._compress_mode.addItem("scale", "按比例")
        self._compress_mode.addItem("quality", "指定质量")
        self._compress_mode.setCurrentItem("target_size")
        self._compress_mode.currentItemChanged.connect(self._on_compress_mode_changed)
        s_l.addWidget(self._compress_mode)

        self._compress_target_panel = QWidget()
        tp_l = QVBoxLayout(self._compress_target_panel)
        tp_l.setContentsMargins(0, 0, 0, 0)
        tp_l.setSpacing(6)
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(CaptionLabel("不超过："))
        self._compress_target_value = SpinBox()
        self._compress_target_value.setRange(1, 99999)
        self._compress_target_value.setValue(500)
        self._compress_target_value.setMinimumWidth(88)
        size_row.addWidget(self._compress_target_value)
        self._compress_target_unit = StudioComboBox()
        self._compress_target_unit.addItems(["KB", "MB"])
        self._compress_target_unit.setMinimumWidth(72)
        size_row.addWidget(self._compress_target_unit)
        size_row.addStretch()
        tp_l.addLayout(size_row)
        tp_l.addWidget(CaptionLabel(
            "自动调节质量与尺寸，使输出尽量接近上限且不超过（推荐 JPEG/WebP）"
        ))
        s_l.addWidget(self._compress_target_panel)

        self._compress_scale_panel = QWidget()
        sp_l = QHBoxLayout(self._compress_scale_panel)
        sp_l.setContentsMargins(0, 0, 0, 0)
        sp_l.addWidget(CaptionLabel("缩放至原图的："))
        self._compress_scale = SpinBox()
        self._compress_scale.setRange(5, 100)
        self._compress_scale.setValue(80)
        self._compress_scale.setSuffix("%")
        self._compress_scale.setMinimumWidth(88)
        sp_l.addWidget(self._compress_scale)
        sp_l.addStretch()
        s_l.addWidget(self._compress_scale_panel)
        self._compress_scale_panel.setVisible(False)

        self._compress_quality_panel = QWidget()
        qp_l = QHBoxLayout(self._compress_quality_panel)
        qp_l.setContentsMargins(0, 0, 0, 0)
        qp_l.addWidget(CaptionLabel("输出质量："))
        self._compress_quality = SpinBox()
        self._compress_quality.setRange(10, 100)
        self._compress_quality.setValue(85)
        self._compress_quality.setMinimumWidth(88)
        qp_l.addWidget(self._compress_quality)
        qp_l.addStretch()
        s_l.addWidget(self._compress_quality_panel)
        self._compress_quality_panel.setVisible(False)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(8)
        fmt_row.addWidget(CaptionLabel("输出格式："))
        self._compress_fmt = StudioComboBox()
        self._compress_fmt.addItems(["自动", "JPEG", "WebP", "PNG"])
        self._compress_fmt.setMinimumWidth(120)
        fmt_row.addWidget(self._compress_fmt, 1)
        s_l.addLayout(fmt_row)

        self._compress_webp_lossless = CheckBox("WebP 无损")
        self._compress_webp_lossless.setVisible(False)
        s_l.addWidget(self._compress_webp_lossless)
        self._compress_fmt.currentTextChanged.connect(self._on_compress_fmt_changed)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self._compress_out = LineEdit()
        self._compress_out.setPlaceholderText("输出目录")
        browse = PushButton("浏览")
        browse.setFixedWidth(64)
        browse.clicked.connect(lambda: self._compress_out.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._compress_out.text()
        ))
        out_row.addWidget(self._compress_out, 1)
        out_row.addWidget(browse)
        s_l.addLayout(out_row)

        left_l.addWidget(s_card)

        self._compress_btn = PrimaryPushButton(FluentIcon.ZIP_FOLDER, "开始压缩")
        self._compress_btn.setFixedHeight(38)
        self._compress_btn.clicked.connect(self._start_compress)
        left_l.addWidget(self._compress_btn)

        self._compress_progress = TaskProgressCard("准备就绪")
        self._compress_progress.setVisible(False)
        left_l.addWidget(self._compress_progress)
        left_l.addStretch()

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)
        right_l.addWidget(CaptionLabel("待压缩文件"))
        self._compress_list = QListWidget()
        apply_list_widget_style(self._compress_list)
        right_l.addWidget(self._compress_list, 1)
        self._compress_count = CaptionLabel("共 0 张图片")
        self._compress_count.setStyleSheet("color:#888;")
        right_l.addWidget(self._compress_count)

        self._on_compress_fmt_changed(self._compress_fmt.currentText())

        layout.addWidget(left)
        layout.addWidget(right, 1)
        return widget

    def _on_compress_mode_changed(self, key: str) -> None:
        self._compress_target_panel.setVisible(key == "target_size")
        self._compress_scale_panel.setVisible(key == "scale")
        self._compress_quality_panel.setVisible(key == "quality")

    def _on_compress_fmt_changed(self, fmt: str) -> None:
        self._compress_webp_lossless.setVisible(fmt.upper() == "WEBP")

    def _compress_filter_paths(self, paths: list[str]) -> list[str]:
        from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
        return [p for p in paths if Path(p).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS]

    def _compress_refresh_list(self) -> None:
        self._compress_list.clear()
        for p in self._compress_paths:
            item = QListWidgetItem(f"{Path(p).name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self._compress_list.addItem(item)
        self._compress_count.setText(f"共 {len(self._compress_paths)} 张图片")

    def _compress_add_files(self, paths: list[str]) -> None:
        valid = self._compress_filter_paths(paths)
        for p in valid:
            if p not in self._compress_paths:
                self._compress_paths.append(p)
        skipped = len(paths) - len(valid)
        if skipped:
            show_warning(self, "部分文件已跳过", f"已跳过 {skipped} 个非图片文件")
        self._compress_refresh_list()

    def _compress_browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.gif);;所有文件 (*.*)",
        )
        if paths:
            self._compress_add_files(paths)

    def _compress_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
            imgs = [str(p) for p in collect_files(folder, SUPPORTED_IMAGE_EXTENSIONS)]
            self._compress_add_files(imgs)

    def _compress_clear(self) -> None:
        self._compress_paths.clear()
        self._compress_refresh_list()

    def _compress_target_bytes(self) -> int:
        value = self._compress_target_value.value()
        unit = self._compress_target_unit.currentText().upper()
        if unit == "MB":
            return value * 1024 * 1024
        return value * 1024

    def _compress_build_options(self, out_dir: str) -> ImageCompressOptions:
        mode = self._compress_mode.currentRouteKey() or "target_size"
        fmt_map = {"自动": "auto", "JPEG": "JPEG", "WebP": "WEBP", "PNG": "PNG"}
        return ImageCompressOptions(
            output_dir=Path(out_dir),
            mode=mode,
            target_max_bytes=self._compress_target_bytes(),
            scale_percent=self._compress_scale.value(),
            jpeg_quality=self._compress_quality.value(),
            output_format=fmt_map.get(self._compress_fmt.currentText(), "auto"),
            webp_lossless=self._compress_webp_lossless.isChecked(),
        )

    def _start_compress(self) -> None:
        if not self._compress_paths:
            show_warning(self, "请先添加图片")
            return
        out_dir = self._compress_out.text().strip()
        if not out_dir:
            out_dir = str(settings_mgr.resolve_output_dir(self._compress_paths[0]))
            self._compress_out.setText(out_dir)

        if self._compress_mode.currentRouteKey() == "target_size":
            if self._compress_target_bytes() < 1024:
                show_warning(self, "目标大小过小", "请设置至少 1 KB")
                return
            if self._compress_fmt.currentText() == "PNG":
                show_info(
                    self, "提示",
                    "PNG 为无损格式，目标大小模式将自动使用 JPEG 编码以控制体积",
                )

        options = self._compress_build_options(out_dir)
        self._compress_btn.setEnabled(False)
        self._compress_progress.setVisible(True)
        w = ImageCompressWorker(self._compress_paths, options)
        w.signals.progress.connect(self._compress_progress.update_progress)
        w.signals.finished.connect(lambda results: (
            self._compress_btn.setEnabled(True),
            self._compress_progress.set_finished(True, f"完成 {len(results)} 张"),
            finish_output_task(
                self,
                self._format_compress_summary(results),
                results[0].output_path if results else out_dir,
            ),
        ))
        w.signals.error.connect(lambda msg: (
            self._compress_btn.setEnabled(True),
            self._compress_progress.set_finished(False, msg),
            show_error(self, "压缩失败", msg),
        ))
        submit_worker(w)

    @staticmethod
    def _format_compress_summary(results) -> str:
        if not results:
            return "压缩完成"
        total_in = sum(r.original_size for r in results)
        total_out = sum(r.compressed_size for r in results)
        if total_in <= 0:
            return f"已压缩 {len(results)} 张图片"
        saved = (1 - total_out / total_in) * 100
        return f"已压缩 {len(results)} 张，总体积减少 {saved:.1f}%"

    # ── 图片→PDF Tab ──────────────────────────

    def _build_image_to_pdf_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(340)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(12)

        drop = DropZone("image", "拖放图片文件到此处")
        drop.filesDropped.connect(self._i2p_add_images)
        left_l.addWidget(drop)

        btn_row = QHBoxLayout()
        add_btn = PushButton(FluentIcon.FOLDER, "添加文件夹")
        add_btn.clicked.connect(self._i2p_add_folder)
        clear_btn = PushButton("清空")
        clear_btn.clicked.connect(self._i2p_clear)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        left_l.addLayout(btn_row)

        self._i2p_count = CaptionLabel("共 0 张图片")
        left_l.addWidget(self._i2p_count)

        s_card = CardWidget()
        s_l = QVBoxLayout(s_card)
        s_l.setContentsMargins(14, 12, 14, 12)
        s_l.setSpacing(8)

        lay_row = QHBoxLayout()
        lay_row.addWidget(CaptionLabel("布局："))
        self._i2p_layout = StudioComboBox()
        self._i2p_layout.addItems(["单图单页", "九宫格（3×3）"])
        lay_row.addWidget(self._i2p_layout)
        lay_row.addStretch()
        s_l.addLayout(lay_row)

        size_row = QHBoxLayout()
        size_row.addWidget(CaptionLabel("页面尺寸："))
        self._i2p_size = StudioComboBox()
        self._i2p_size.addItems(["A4", "A3", "Letter", "原始尺寸"])
        size_row.addWidget(self._i2p_size)
        size_row.addStretch()
        s_l.addLayout(size_row)

        self._i2p_auto_resize = CheckBox("自动填满页面")
        self._i2p_auto_resize.setChecked(True)
        s_l.addWidget(self._i2p_auto_resize)

        self._i2p_auto_rotate = CheckBox("自动旋转适配横图")
        self._i2p_auto_rotate.setChecked(True)
        s_l.addWidget(self._i2p_auto_rotate)

        out_row = QHBoxLayout()
        self._i2p_out = LineEdit()
        self._i2p_out.setPlaceholderText("输出PDF路径")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._i2p_out.setText(
            QFileDialog.getSaveFileName(self, "保存PDF", "images.pdf", "PDF (*.pdf)")[0] or self._i2p_out.text()
        ))
        out_row.addWidget(self._i2p_out, 1)
        out_row.addWidget(browse)
        s_l.addLayout(out_row)

        left_l.addWidget(s_card)

        self._i2p_btn = PrimaryPushButton(FluentIcon.DOCUMENT, "转为PDF")
        self._i2p_btn.setFixedHeight(38)
        self._i2p_btn.clicked.connect(self._start_i2p)
        left_l.addWidget(self._i2p_btn)

        self._i2p_progress = TaskProgressCard("准备就绪")
        self._i2p_progress.setVisible(False)
        left_l.addWidget(self._i2p_progress)
        left_l.addStretch()

        self._i2p_thumbs = ThumbnailPanel()
        layout.addWidget(left)
        layout.addWidget(self._i2p_thumbs, 1)
        return widget

    def _i2p_add_images(self, paths):
        from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
        valid = [p for p in paths if Path(p).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS]
        self._image_paths.extend(valid)
        self._i2p_count.setText(f"共 {len(self._image_paths)} 张图片")

    def _i2p_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if folder:
            from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
            imgs = collect_files(folder, SUPPORTED_IMAGE_EXTENSIONS)
            self._image_paths.extend(str(p) for p in imgs)
            self._i2p_count.setText(f"共 {len(self._image_paths)} 张图片")

    def _i2p_clear(self):
        self._image_paths.clear()
        self._i2p_count.setText("共 0 张图片")

    def _start_i2p(self):
        if not self._image_paths:
            show_warning(self, "请先添加图片")
            return
        out = self._i2p_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        layout_map = {"单图单页": "single", "九宫格（3×3）": "grid9"}
        options = ImageToPDFOptions(
            output_path=Path(out),
            layout=layout_map.get(self._i2p_layout.currentText(), "single"),
            page_size=self._i2p_size.currentText(),
            auto_resize=self._i2p_auto_resize.isChecked(),
            auto_rotate=self._i2p_auto_rotate.isChecked(),
        )
        self._i2p_btn.setEnabled(False)
        self._i2p_progress.setVisible(True)
        w = ImageToPDFWorker(self._image_paths, options)
        w.signals.progress.connect(self._i2p_progress.update_progress)
        w.signals.finished.connect(lambda p: (
            self._i2p_btn.setEnabled(True),
            self._i2p_progress.set_finished(True),
            finish_output_task(self, "转换完成", p),
        ))
        w.signals.error.connect(lambda msg: (
            self._i2p_btn.setEnabled(True),
            self._i2p_progress.set_finished(False, msg),
            show_error(self, "转换失败", msg),
        ))
        submit_worker(w)

    # ── 内容提取 Tab ──────────────────────────

    def _build_extract_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放 PDF 文件到此处")
        drop.filesDropped.connect(self._extract_load_pdf)
        layout.addWidget(drop)

        self._extract_file_label = CaptionLabel("")
        self._extract_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._extract_file_label)

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)

        c_l.addWidget(CaptionLabel("页码范围（留空=全部页，例：1-3,5）："))
        self._extract_pages = LineEdit()
        self._extract_pages.setPlaceholderText("留空表示提取全部页面")
        c_l.addWidget(self._extract_pages)

        out_row = QHBoxLayout()
        self._extract_out = LineEdit()
        self._extract_out.setPlaceholderText("输出目录")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._extract_out.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._extract_out.text()
        ))
        out_row.addWidget(self._extract_out, 1)
        out_row.addWidget(browse)
        c_l.addLayout(out_row)

        self._extract_combined = CheckBox("文字合并为单个 TXT 文件")
        self._extract_combined.setChecked(True)
        c_l.addWidget(self._extract_combined)
        layout.addWidget(card)

        btn_row = QHBoxLayout()
        text_btn = PrimaryPushButton(FluentIcon.DOCUMENT, "提取文字")
        text_btn.clicked.connect(self._start_extract_text)
        img_btn = PrimaryPushButton(FluentIcon.PHOTO, "提取内嵌图片")
        img_btn.clicked.connect(self._start_extract_images)
        btn_row.addWidget(text_btn)
        btn_row.addWidget(img_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(CaptionLabel(
            "提取文字：导出 PDF 文字层；扫描件无文字层时请使用 OCR 识别。"
        ))

        self._extract_progress = TaskProgressCard("准备就绪")
        self._extract_progress.setVisible(False)
        layout.addWidget(self._extract_progress)
        layout.addStretch()
        return widget

    def _extract_load_pdf(self, paths: list[str]) -> None:
        if not paths:
            return
        path = paths[0]
        try:
            from core.pdf.processor import PDFReader
            info = PDFReader.get_info(path)
        except Exception as e:
            show_error(self, "加载失败", str(e))
            return
        self._extract_path = path
        self._extract_page_count = info.page_count
        self._extract_file_label.setText(f"{Path(path).name}  ·  {info.page_count} 页")
        out = settings_mgr.resolve_output_dir(path)
        self._extract_out.setText(str(out))

    def _extract_page_indices(self) -> Optional[list[int]]:
        spec = self._extract_pages.text().strip()
        if not spec:
            return None
        from core.pdf.processor import PDFReader
        pages = PDFReader.parse_page_range(spec, self._extract_page_count)
        if not pages:
            raise ValueError("页码范围无效")
        return pages

    def _start_extract_text(self) -> None:
        if not self._extract_path:
            show_warning(self, "请先导入 PDF")
            return
        out_dir = self._extract_out.text().strip()
        if not out_dir:
            show_warning(self, "请设置输出目录")
            return
        try:
            indices = self._extract_page_indices()
        except ValueError as e:
            show_warning(self, str(e))
            return

        self._extract_progress.setVisible(True)
        w = PDFExtractTextWorker(
            self._extract_path,
            out_dir,
            indices,
            combined=self._extract_combined.isChecked(),
        )
        w.signals.progress.connect(self._extract_progress.update_progress)
        w.signals.finished.connect(lambda files: (
            self._extract_progress.set_finished(True, f"共 {len(files)} 个文件"),
            finish_output_task(self, f"已提取 {len(files)} 个文字文件", files[0] if files else out_dir),
        ))
        w.signals.error.connect(lambda msg: (
            self._extract_progress.set_finished(False, msg),
            show_error(self, "提取失败", msg),
        ))
        submit_worker(w)

    def _start_extract_images(self) -> None:
        if not self._extract_path:
            show_warning(self, "请先导入 PDF")
            return
        out_dir = self._extract_out.text().strip()
        if not out_dir:
            show_warning(self, "请设置输出目录")
            return
        try:
            indices = self._extract_page_indices()
        except ValueError as e:
            show_warning(self, str(e))
            return

        self._extract_progress.setVisible(True)
        w = PDFExtractImagesWorker(self._extract_path, out_dir, indices)
        w.signals.progress.connect(self._extract_progress.update_progress)
        w.signals.finished.connect(lambda files: (
            self._extract_progress.set_finished(
                True,
                f"共 {len(files)} 张图片" if files else "未找到内嵌图片",
            ),
            finish_output_task(
                self,
                f"已提取 {len(files)} 张图片" if files else "提取完成",
                str(files[0].parent) if files else out_dir,
            ),
        ))
        w.signals.error.connect(lambda msg: (
            self._extract_progress.set_finished(False, msg),
            show_error(self, "提取失败", msg),
        ))
        submit_worker(w)

    # ── 扫描增强 Tab ──────────────────────────

    def _build_scan_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        drop = DropZone("image", "拖放扫描件/图片（可多选）")
        drop.filesDropped.connect(self._scan_add_files)
        layout.addWidget(drop)

        btn_row = QHBoxLayout()
        add_btn = PushButton("添加图片")
        add_btn.clicked.connect(self._scan_browse)
        folder_btn = PushButton("添加文件夹")
        folder_btn.clicked.connect(self._scan_add_folder)
        clear_btn = PushButton("清空")
        clear_btn.clicked.connect(self._scan_clear)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(folder_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._scan_count = CaptionLabel("共 0 张图片")
        self._scan_count.setStyleSheet("color:#888;")
        layout.addWidget(self._scan_count)

        card = CardWidget()
        c = QVBoxLayout(card)
        c.setContentsMargins(14, 12, 14, 12)
        c.setSpacing(8)
        self._scan_deskew = CheckBox("自动纠偏")
        self._scan_border = CheckBox("去黑边")
        self._scan_denoise = CheckBox("去噪")
        self._scan_gray = CheckBox("灰度化")
        self._scan_binarize = CheckBox("二值化（扫描文档）")
        for cb in (self._scan_deskew, self._scan_border, self._scan_denoise,
                   self._scan_gray, self._scan_binarize):
            c.addWidget(cb)
        self._scan_deskew.setChecked(True)
        self._scan_border.setChecked(True)

        contrast_row = QHBoxLayout()
        contrast_row.addWidget(CaptionLabel("对比度 %："))
        self._scan_contrast = SpinBox()
        self._scan_contrast.setRange(50, 200)
        self._scan_contrast.setValue(100)
        contrast_row.addWidget(self._scan_contrast)
        contrast_row.addWidget(CaptionLabel("亮度 %："))
        self._scan_brightness = SpinBox()
        self._scan_brightness.setRange(50, 200)
        self._scan_brightness.setValue(100)
        contrast_row.addWidget(self._scan_brightness)
        contrast_row.addStretch()
        c.addLayout(contrast_row)
        layout.addWidget(card)

        out_row = QHBoxLayout()
        self._scan_out = LineEdit()
        self._scan_out.setPlaceholderText("输出目录")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._scan_out.setText(
            QFileDialog.getExistingDirectory(self, "选择输出目录") or self._scan_out.text()
        ))
        out_row.addWidget(self._scan_out, 1)
        out_row.addWidget(browse)
        layout.addLayout(out_row)

        self._scan_btn = PrimaryPushButton(FluentIcon.PHOTO, "开始增强")
        self._scan_btn.clicked.connect(self._start_scan)
        layout.addWidget(self._scan_btn)

        self._scan_send_merge_btn = PushButton(FluentIcon.SHARE, "送到图片合并")
        self._scan_send_merge_btn.setEnabled(False)
        self._scan_send_merge_btn.setToolTip("将最近一次增强输出的图片导入「图片合并」列表")
        self._scan_send_merge_btn.clicked.connect(self._scan_send_to_merge)
        layout.addWidget(self._scan_send_merge_btn)

        self._scan_progress = TaskProgressCard("准备就绪")
        self._scan_progress.setVisible(False)
        layout.addWidget(self._scan_progress)
        layout.addStretch()
        return widget

    def _scan_add_files(self, paths: list[str]) -> None:
        self._scan_paths.extend(paths)
        self._scan_count.setText(f"共 {len(self._scan_paths)} 张图片")

    def _scan_browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp);;所有文件 (*.*)",
        )
        if paths:
            self._scan_add_files(paths)

    def _scan_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            from app.config.constants import SUPPORTED_IMAGE_EXTENSIONS
            imgs = [str(p) for p in collect_files(folder, SUPPORTED_IMAGE_EXTENSIONS)]
            self._scan_add_files(imgs)

    def _scan_clear(self) -> None:
        self._scan_paths.clear()
        self._scan_count.setText("共 0 张图片")

    def _start_scan(self) -> None:
        if not self._scan_paths:
            show_warning(self, "请先添加图片")
            return
        out_dir = self._scan_out.text().strip()
        if not out_dir:
            show_warning(self, "请设置输出目录")
            return
        options = ImageEnhanceOptions(
            contrast=self._scan_contrast.value() / 100.0,
            brightness=self._scan_brightness.value() / 100.0,
            denoise=self._scan_denoise.isChecked(),
            grayscale=self._scan_gray.isChecked(),
            binarize=self._scan_binarize.isChecked(),
            deskew=self._scan_deskew.isChecked(),
            remove_border=self._scan_border.isChecked(),
        )
        self._scan_btn.setEnabled(False)
        self._scan_progress.setVisible(True)
        w = ImageEnhanceWorker(self._scan_paths, out_dir, options)
        w.signals.progress.connect(self._scan_progress.update_progress)
        w.signals.finished.connect(lambda outputs: (
            self._scan_btn.setEnabled(True),
            self._scan_progress.set_finished(True, f"完成 {len(outputs)} 张"),
            self._scan_set_last_outputs(outputs),
            finish_output_task(self, "扫描增强完成", out_dir),
        ))
        w.signals.error.connect(lambda msg: (
            self._scan_btn.setEnabled(True),
            self._scan_progress.set_finished(False, msg),
            show_error(self, "增强失败", msg),
        ))
        submit_worker(w)

    def _scan_set_last_outputs(self, outputs) -> None:
        self._scan_last_outputs = [str(p) for p in outputs if Path(p).is_file()]
        self._scan_send_merge_btn.setEnabled(bool(self._scan_last_outputs))

    def _scan_send_to_merge(self) -> None:
        if not self._scan_last_outputs:
            show_warning(self, "暂无增强结果", "请先完成一次扫描增强")
            return
        added = self._merge_list.add_files(self._scan_last_outputs)
        self._image_tabs.setCurrentIndex(1)
        show_info(self, "已导入", f"已将 {added} 张增强图加入图片合并列表")
