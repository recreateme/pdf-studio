"""
PDF Studio - 设置页面
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton,
    SpinBox, DoubleSpinBox, StrongBodyLabel, FluentIcon, LineEdit,
    SwitchButton, BodyLabel, SubtitleLabel, setTheme, Theme,
)

from app.config.settings import settings_mgr, AppSettings
from app.config.constants import APP_VERSION
from app.widgets.common import show_success, show_info, show_error, show_warning
from app.widgets.combo_box import StudioComboBox
from app.utils.helpers import clean_temp, open_in_explorer
from app.utils.logger import logger


class SettingRow(QWidget):
    """设置行：左侧标签+说明，右侧控件（右侧保留固定宽度，避免 SpinBox 被挤压）"""

    SPIN_CONTROL_WIDTH = 172
    SPIN_SUFFIX_CONTROL_WIDTH = 192
    COMBO_CONTROL_WIDTH = 208

    def __init__(
        self,
        title: str,
        desc: str = "",
        *,
        control_width: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(20)

        text_widget = QWidget()
        text_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_l = QVBoxLayout(text_widget)
        text_l.setContentsMargins(0, 0, 0, 0)
        text_l.setSpacing(2)
        text_l.addWidget(BodyLabel(title))
        if desc:
            d = CaptionLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet("color:#888;")
            text_l.addWidget(d)

        self._control_host = QWidget()
        self._control_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if control_width > 0:
            self._control_host.setMinimumWidth(control_width)
            self._control_host.setFixedWidth(control_width)
        host_layout = QHBoxLayout(self._control_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(8)
        host_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(text_widget, 1)
        layout.addWidget(
            self._control_host,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

    def add_control(self, widget):
        self._control_host.layout().addWidget(widget)
        return widget


class SettingsPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._setup_ui()
        self._load_from_settings()

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 36)
        root.setSpacing(24)

        root.addWidget(TitleLabel("设置"))
        root.addWidget(CaptionLabel(f"PDF Studio  v{APP_VERSION}"))

        # ── 外观 ───────────────────────────────
        root.addWidget(SubtitleLabel("外观"))
        appear_card = CardWidget()
        ap_l = QVBoxLayout(appear_card)
        ap_l.setContentsMargins(20, 16, 20, 16)
        ap_l.setSpacing(4)

        theme_row = SettingRow("主题模式", "深色/浅色/跟随系统", control_width=SettingRow.COMBO_CONTROL_WIDTH)
        self._theme_combo = self._make_combo()
        self._theme_combo.addItems(["跟随系统", "浅色", "深色"])
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.add_control(self._theme_combo)
        ap_l.addWidget(theme_row)
        ap_l.addWidget(self._separator())

        label_row = SettingRow("显示导航栏标签", "关闭后导航栏仅显示图标")
        self._toolbar_labels = SwitchButton()
        label_row.add_control(self._toolbar_labels)
        ap_l.addWidget(label_row)

        root.addWidget(appear_card)

        # ── PDF处理 ────────────────────────────
        root.addWidget(SubtitleLabel("PDF 处理"))
        pdf_card = CardWidget()
        pdf_l = QVBoxLayout(pdf_card)
        pdf_l.setContentsMargins(20, 16, 20, 16)
        pdf_l.setSpacing(4)

        dpi_row = SettingRow(
            "默认渲染 DPI",
            "影响 PDF 转图片、OCR 等功能的默认分辨率；各功能页首次打开时会读取此值",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._default_dpi = self._make_spin(72, 600)
        dpi_row.add_control(self._default_dpi)
        pdf_l.addWidget(dpi_row)
        pdf_l.addWidget(self._separator())

        thumb_row = SettingRow(
            "缩略图宽度（px）",
            "预览面板中单页缩略图的宽度；重新打开 PDF 后生效",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._thumb_size = self._make_spin(80, 320)
        thumb_row.add_control(self._thumb_size)
        pdf_l.addWidget(thumb_row)
        pdf_l.addWidget(self._separator())

        cache_row = SettingRow("启用页面缓存", "缓存已渲染的缩略图，减少重复计算")
        self._cache_cb = SwitchButton()
        cache_row.add_control(self._cache_cb)
        pdf_l.addWidget(cache_row)
        pdf_l.addWidget(self._separator())

        cache_pages_row = SettingRow(
            "页面缓存上限",
            "最多缓存的 PDF 页数",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._cache_max_pages = self._make_spin(10, 500)
        cache_pages_row.add_control(self._cache_max_pages)
        pdf_l.addWidget(cache_pages_row)
        pdf_l.addWidget(self._separator())

        compress_row = SettingRow(
            "默认压缩模式",
            "压缩页面的初始模式",
            control_width=SettingRow.COMBO_CONTROL_WIDTH,
        )
        self._compress_mode = self._make_combo()
        self._compress_mode.addItems(["高质量（轻度压缩）", "均衡模式（推荐）", "极限压缩"])
        compress_row.add_control(self._compress_mode)
        pdf_l.addWidget(compress_row)
        pdf_l.addWidget(self._separator())

        out_row = SettingRow("默认输出目录", "留空则各功能输出到源文件同目录", control_width=320)
        self._default_out = LineEdit()
        self._default_out.setPlaceholderText("默认：与源文件同目录")
        self._default_out.setMinimumWidth(200)
        browse_btn = PushButton("浏览")
        browse_btn.setFixedWidth(56)
        browse_btn.clicked.connect(self._browse_output_dir)
        out_row.add_control(self._default_out)
        out_row.add_control(browse_btn)
        pdf_l.addWidget(out_row)

        root.addWidget(pdf_card)

        # ── OCR 设置 ───────────────────────────
        root.addWidget(SubtitleLabel("OCR 识别"))
        ocr_card = CardWidget()
        ocr_l = QVBoxLayout(ocr_card)
        ocr_l.setContentsMargins(20, 16, 20, 16)
        ocr_l.setSpacing(4)

        engine_row = SettingRow(
            "OCR 引擎",
            "RapidOCR（推荐，轻量）或 PaddleOCR（精度更高）",
            control_width=SettingRow.COMBO_CONTROL_WIDTH,
        )
        self._ocr_engine = self._make_combo()
        self._ocr_engine.addItems(["RapidOCR（推荐）", "PaddleOCR"])
        engine_row.add_control(self._ocr_engine)
        ocr_l.addWidget(engine_row)
        ocr_l.addWidget(self._separator())

        ocr_dpi_row = SettingRow(
            "默认识别 DPI",
            "OCR 页面打开时的默认渲染 DPI",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._ocr_default_dpi = self._make_spin(72, 400)
        ocr_dpi_row.add_control(self._ocr_default_dpi)
        ocr_l.addWidget(ocr_dpi_row)
        ocr_l.addWidget(self._separator())

        conf_row = SettingRow(
            "默认置信度阈值",
            "低于此值的识别结果将被丢弃（%）",
            control_width=SettingRow.SPIN_SUFFIX_CONTROL_WIDTH,
        )
        self._ocr_confidence = self._make_spin(0, 100, with_suffix=True)
        conf_row.add_control(self._ocr_confidence)
        ocr_l.addWidget(conf_row)
        ocr_l.addWidget(self._separator())

        fmt_row = SettingRow(
            "默认导出格式",
            "OCR 识别完成后的默认保存格式",
            control_width=SettingRow.COMBO_CONTROL_WIDTH,
        )
        self._ocr_format = self._make_combo()
        self._ocr_format.addItems(["TXT", "DOCX", "Markdown", "JSON", "可搜索PDF"])
        fmt_row.add_control(self._ocr_format)
        ocr_l.addWidget(fmt_row)
        ocr_l.addWidget(self._separator())

        gpu_row = SettingRow("使用 GPU 加速", "需要 CUDA 环境，无 GPU 时自动回退到 CPU")
        self._use_gpu = SwitchButton()
        gpu_row.add_control(self._use_gpu)
        ocr_l.addWidget(gpu_row)
        ocr_l.addWidget(self._separator())

        det_row = SettingRow(
            "检测模型路径",
            "留空使用内置模型；可指定自定义 ONNX 检测模型",
            control_width=320,
        )
        self._det_model = LineEdit()
        self._det_model.setPlaceholderText("可选")
        self._det_model.setMinimumWidth(200)
        det_browse = PushButton("浏览")
        det_browse.setFixedWidth(56)
        det_browse.clicked.connect(lambda: self._browse_model_file(self._det_model))
        det_row.add_control(self._det_model)
        det_row.add_control(det_browse)
        ocr_l.addWidget(det_row)
        ocr_l.addWidget(self._separator())

        rec_row = SettingRow(
            "识别模型路径",
            "留空使用内置模型；可指定自定义 ONNX 识别模型",
            control_width=320,
        )
        self._rec_model = LineEdit()
        self._rec_model.setPlaceholderText("可选")
        self._rec_model.setMinimumWidth(200)
        rec_browse = PushButton("浏览")
        rec_browse.setFixedWidth(56)
        rec_browse.clicked.connect(lambda: self._browse_model_file(self._rec_model))
        rec_row.add_control(self._rec_model)
        rec_row.add_control(rec_browse)
        ocr_l.addWidget(rec_row)
        ocr_l.addWidget(self._separator())

        cls_row = SettingRow(
            "方向分类模型路径",
            "留空使用内置模型；可指定自定义 ONNX 分类模型",
            control_width=320,
        )
        self._cls_model = LineEdit()
        self._cls_model.setPlaceholderText("可选")
        self._cls_model.setMinimumWidth(200)
        cls_browse = PushButton("浏览")
        cls_browse.setFixedWidth(56)
        cls_browse.clicked.connect(lambda: self._browse_model_file(self._cls_model))
        cls_row.add_control(self._cls_model)
        cls_row.add_control(cls_browse)
        ocr_l.addWidget(cls_row)

        root.addWidget(ocr_card)

        # ── 网页转 PDF ─────────────────────────
        root.addWidget(SubtitleLabel("网页转 PDF"))
        web_card = CardWidget()
        web_l = QVBoxLayout(web_card)
        web_l.setContentsMargins(20, 16, 20, 16)
        web_l.setSpacing(4)

        web_timeout_row = SettingRow(
            "页面加载超时（秒）",
            "网页转 PDF 页面的默认超时",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._web_timeout = self._make_spin(5, 300)
        web_timeout_row.add_control(self._web_timeout)
        web_l.addWidget(web_timeout_row)
        web_l.addWidget(self._separator())

        web_format_row = SettingRow(
            "默认页面格式",
            "导出 PDF 的纸张规格",
            control_width=SettingRow.COMBO_CONTROL_WIDTH,
        )
        self._web_page_format = self._make_combo()
        self._web_page_format.addItems(["A4", "A3", "Letter", "Legal"])
        web_format_row.add_control(self._web_page_format)
        web_l.addWidget(web_format_row)
        web_l.addWidget(self._separator())

        scroll_wait_row = SettingRow(
            "滚动等待（秒）",
            "懒加载页面每次滚动后的等待时间",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._web_scroll_wait = self._make_double_spin(0.1, 5.0, step=0.1)
        scroll_wait_row.add_control(self._web_scroll_wait)
        web_l.addWidget(scroll_wait_row)
        web_l.addWidget(self._separator())

        scroll_times_row = SettingRow(
            "最大滚动次数",
            "触发懒加载时的滚动上限",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._web_max_scroll = self._make_spin(1, 100)
        scroll_times_row.add_control(self._web_max_scroll)
        web_l.addWidget(scroll_times_row)
        web_l.addWidget(self._separator())

        margin_row = SettingRow(
            "页边距（mm）",
            "导出 PDF 的四边统一边距",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._web_margin = self._make_spin(0, 50)
        margin_row.add_control(self._web_margin)
        web_l.addWidget(margin_row)
        web_l.addWidget(self._separator())

        web_bg_row = SettingRow("打印背景色/图片", "网页转 PDF 时保留页面背景")
        self._web_print_bg = SwitchButton()
        web_bg_row.add_control(self._web_print_bg)
        web_l.addWidget(web_bg_row)
        web_l.addWidget(self._separator())

        web_js_row = SettingRow("执行 JavaScript", "关闭后仅渲染静态 HTML")
        self._web_enable_js = SwitchButton()
        web_js_row.add_control(self._web_enable_js)
        web_l.addWidget(web_js_row)
        web_l.addWidget(self._separator())

        web_parallel_row = SettingRow(
            "批量 URL 并行数",
            "网页转 PDF 批量模式同时打开的浏览器数（1–4）",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._web_batch_parallel = self._make_spin(1, 4)
        web_parallel_row.add_control(self._web_batch_parallel)
        web_l.addWidget(web_parallel_row)

        root.addWidget(web_card)

        # ── 批处理工作流 ───────────────────────
        root.addWidget(SubtitleLabel("批处理工作流"))
        wf_card = CardWidget()
        wf_l = QVBoxLayout(wf_card)
        wf_l.setContentsMargins(20, 16, 20, 16)
        wf_l.setSpacing(4)

        retry_row = SettingRow("失败自动重试", "单个步骤失败时按下方次数重试")
        self._wf_auto_retry = SwitchButton()
        retry_row.add_control(self._wf_auto_retry)
        wf_l.addWidget(retry_row)
        wf_l.addWidget(self._separator())

        retry_count_row = SettingRow(
            "重试次数",
            "每个失败步骤的最大尝试次数",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._wf_retry_count = self._make_spin(1, 10)
        retry_count_row.add_control(self._wf_retry_count)
        wf_l.addWidget(retry_count_row)
        wf_l.addWidget(self._separator())

        queue_row = SettingRow(
            "任务队列上限",
            "进行中 + 排队任务总数上限；满后将拒绝新任务并提示",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._wf_queue_max = self._make_spin(10, 1000)
        queue_row.add_control(self._wf_queue_max)
        wf_l.addWidget(queue_row)
        wf_l.addWidget(self._separator())

        history_row = SettingRow("保存工作流历史", "记录批处理执行摘要（预留）")
        self._wf_save_history = SwitchButton()
        history_row.add_control(self._wf_save_history)
        wf_l.addWidget(history_row)

        root.addWidget(wf_card)

        # ── 线程与性能 ─────────────────────────
        root.addWidget(SubtitleLabel("性能"))
        perf_card = CardWidget()
        perf_l = QVBoxLayout(perf_card)
        perf_l.setContentsMargins(20, 16, 20, 16)
        perf_l.setSpacing(4)

        thread_row = SettingRow(
            "最大工作线程数",
            "后台任务并发数，保存后立即生效",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._max_workers = self._make_spin(1, 16)
        thread_row.add_control(self._max_workers)
        perf_l.addWidget(thread_row)

        root.addWidget(perf_card)

        # ── 日志 ───────────────────────────────
        root.addWidget(SubtitleLabel("日志"))
        log_card = CardWidget()
        log_l = QVBoxLayout(log_card)
        log_l.setContentsMargins(20, 16, 20, 16)
        log_l.setSpacing(4)

        level_row = SettingRow(
            "日志级别",
            "保存后立即生效",
            control_width=SettingRow.COMBO_CONTROL_WIDTH,
        )
        self._log_level = self._make_combo()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        level_row.add_control(self._log_level)
        log_l.addWidget(level_row)
        log_l.addWidget(self._separator())

        open_log_row = SettingRow("查看日志文件", "在文件管理器中打开日志目录")
        open_log_btn = PushButton("打开日志目录")
        open_log_btn.clicked.connect(self._open_log_dir)
        open_log_row.add_control(open_log_btn)
        log_l.addWidget(open_log_row)

        root.addWidget(log_card)

        # ── 缓存与最近文件 ─────────────────────
        root.addWidget(SubtitleLabel("数据管理"))
        data_card = CardWidget()
        data_l = QVBoxLayout(data_card)
        data_l.setContentsMargins(20, 16, 20, 16)
        data_l.setSpacing(4)

        recent_row = SettingRow(
            "最大最近文件数",
            "首页显示的最近文件记录上限",
            control_width=SettingRow.SPIN_CONTROL_WIDTH,
        )
        self._max_recent = self._make_spin(5, 100)
        recent_row.add_control(self._max_recent)
        data_l.addWidget(recent_row)
        data_l.addWidget(self._separator())

        clean_row = SettingRow("清理临时文件", "删除处理过程中生成的临时文件")
        clean_btn = PushButton("立即清理")
        clean_btn.clicked.connect(self._clean_temp)
        clean_row.add_control(clean_btn)
        data_l.addWidget(clean_row)

        root.addWidget(data_card)

        save_row = QHBoxLayout()
        save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存设置")
        save_btn.setFixedHeight(40)
        save_btn.setFixedWidth(160)
        save_btn.clicked.connect(self._save)
        reset_btn = PushButton("恢复默认")
        reset_btn.setFixedHeight(40)
        reset_btn.setFixedWidth(120)
        reset_btn.clicked.connect(self._reset)
        save_row.addStretch()
        save_row.addWidget(reset_btn)
        save_row.addWidget(save_btn)
        root.addLayout(save_row)
        root.addStretch()

    def _make_combo(self) -> StudioComboBox:
        return StudioComboBox(width=SettingRow.COMBO_CONTROL_WIDTH)

    def _make_spin(self, minimum: int, maximum: int, *, with_suffix: bool = False) -> SpinBox:
        spin = SpinBox()
        spin.setRange(minimum, maximum)
        spin.setAccelerated(True)
        spin.setKeyboardTracking(True)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        width = (
            SettingRow.SPIN_SUFFIX_CONTROL_WIDTH
            if with_suffix
            else SettingRow.SPIN_CONTROL_WIDTH
        )
        spin.setFixedWidth(width)
        spin.setMinimumWidth(width)
        if with_suffix:
            spin.setSuffix(" %")
        return spin

    def _make_double_spin(
        self,
        minimum: float,
        maximum: float,
        *,
        step: float = 0.5,
    ) -> DoubleSpinBox:
        spin = DoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(1)
        spin.setAccelerated(True)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setFixedWidth(SettingRow.SPIN_CONTROL_WIDTH)
        spin.setMinimumWidth(SettingRow.SPIN_CONTROL_WIDTH)
        return spin

    def _separator(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(128,128,128,0.15);")
        return line

    def _load_from_settings(self) -> None:
        """从配置管理器刷新所有控件显示"""
        g = settings_mgr.general
        p = settings_mgr.pdf
        o = settings_mgr.ocr
        w = settings_mgr.web
        wf = settings_mgr.workflow
        lg = settings_mgr.log

        self._theme_combo.blockSignals(True)
        theme_map = {"auto": 0, "light": 1, "dark": 2}
        self._theme_combo.setCurrentIndex(theme_map.get(g.theme, 0))
        self._theme_combo.blockSignals(False)

        self._toolbar_labels.setChecked(g.show_toolbar_labels)
        self._max_recent.setValue(g.max_recent_files)

        self._default_dpi.setValue(p.default_dpi)
        self._thumb_size.setValue(p.thumbnail_size)
        self._cache_cb.setChecked(p.enable_page_cache)
        self._cache_max_pages.setValue(p.cache_max_pages)
        self._default_out.setText(p.default_output_dir)

        compress_map = {"high_quality": 0, "balanced": 1, "max_compress": 2}
        self._compress_mode.setCurrentIndex(compress_map.get(p.compression_level, 1))

        self._ocr_engine.setCurrentIndex(0 if o.engine == "rapidocr" else 1)
        self._ocr_default_dpi.setValue(o.default_dpi)
        self._ocr_confidence.setValue(int(round(o.confidence_threshold * 100)))
        self._use_gpu.setChecked(o.use_gpu)

        fmt_display = {
            "txt": "TXT",
            "docx": "DOCX",
            "markdown": "Markdown",
            "json": "JSON",
            "searchable_pdf": "可搜索PDF",
        }
        self._ocr_format.setCurrentText(fmt_display.get(o.output_format, "TXT"))

        self._det_model.setText(o.det_model_path)
        self._rec_model.setText(o.rec_model_path)
        self._cls_model.setText(o.cls_model_path)

        self._web_timeout.setValue(w.wait_timeout)
        idx = self._web_page_format.findText(w.page_format)
        if idx >= 0:
            self._web_page_format.setCurrentIndex(idx)
        self._web_scroll_wait.setValue(w.scroll_wait)
        self._web_max_scroll.setValue(w.max_scroll_times)
        self._web_margin.setValue(int(w.margin_top))
        self._web_print_bg.setChecked(w.print_background)
        self._web_enable_js.setChecked(w.enable_javascript)
        self._web_batch_parallel.setValue(w.batch_concurrency)

        self._wf_auto_retry.setChecked(wf.auto_retry_on_failure)
        self._wf_retry_count.setValue(wf.retry_count)
        self._wf_queue_max.setValue(wf.queue_max_size)
        self._wf_save_history.setChecked(wf.save_workflow_history)

        self._max_workers.setValue(wf.max_workers)

        level_map = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        self._log_level.setCurrentIndex(level_map.get(lg.level, 1))

    def _on_theme_changed(self, idx: int):
        theme_list = [Theme.AUTO, Theme.LIGHT, Theme.DARK]
        setTheme(theme_list[idx])

    def _browse_output_dir(self):
        current = self._default_out.text().strip()
        d = QFileDialog.getExistingDirectory(self, "选择默认输出目录", current or "")
        if d:
            self._default_out.setText(d)

    def _browse_model_file(self, line_edit: LineEdit) -> None:
        current = line_edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ONNX 模型文件",
            current or "",
            "ONNX 模型 (*.onnx);;所有文件 (*.*)",
        )
        if path:
            line_edit.setText(path)

    def _open_log_dir(self):
        from app.config.constants import LOGS_DIR

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        open_in_explorer(LOGS_DIR)

    def _clean_temp(self):
        clean_temp()
        show_success(self.window(), "临时文件已清理")

    def _save(self):
        try:
            s = settings_mgr.settings

            theme_keys = ["auto", "light", "dark"]
            s.general.theme = theme_keys[self._theme_combo.currentIndex()]
            s.general.show_toolbar_labels = self._toolbar_labels.isChecked()
            s.general.max_recent_files = self._max_recent.value()

            s.pdf.default_dpi = self._default_dpi.value()
            s.pdf.thumbnail_size = self._thumb_size.value()
            s.pdf.enable_page_cache = self._cache_cb.isChecked()
            s.pdf.cache_max_pages = self._cache_max_pages.value()
            s.pdf.default_output_dir = self._default_out.text().strip()

            compress_keys = ["high_quality", "balanced", "max_compress"]
            s.pdf.compression_level = compress_keys[self._compress_mode.currentIndex()]

            engine_keys = ["rapidocr", "paddleocr"]
            s.ocr.engine = engine_keys[self._ocr_engine.currentIndex()]
            s.ocr.default_dpi = self._ocr_default_dpi.value()
            s.ocr.confidence_threshold = self._ocr_confidence.value() / 100.0
            s.ocr.use_gpu = self._use_gpu.isChecked()
            s.ocr.det_model_path = self._det_model.text().strip()
            s.ocr.rec_model_path = self._rec_model.text().strip()
            s.ocr.cls_model_path = self._cls_model.text().strip()

            fmt_map = {
                "TXT": "txt",
                "DOCX": "docx",
                "Markdown": "markdown",
                "JSON": "json",
                "可搜索PDF": "searchable_pdf",
            }
            s.ocr.output_format = fmt_map.get(self._ocr_format.currentText(), "txt")

            s.web.wait_timeout = self._web_timeout.value()
            s.web.page_format = self._web_page_format.currentText()
            s.web.scroll_wait = self._web_scroll_wait.value()
            s.web.max_scroll_times = self._web_max_scroll.value()
            margin = float(self._web_margin.value())
            s.web.margin_top = margin
            s.web.margin_bottom = margin
            s.web.margin_left = margin
            s.web.margin_right = margin
            s.web.print_background = self._web_print_bg.isChecked()
            s.web.enable_javascript = self._web_enable_js.isChecked()
            s.web.batch_concurrency = self._web_batch_parallel.value()

            s.workflow.auto_retry_on_failure = self._wf_auto_retry.isChecked()
            s.workflow.retry_count = self._wf_retry_count.value()
            s.workflow.queue_max_size = self._wf_queue_max.value()
            s.workflow.save_workflow_history = self._wf_save_history.isChecked()
            s.workflow.max_workers = self._max_workers.value()

            level_keys = ["DEBUG", "INFO", "WARNING", "ERROR"]
            s.log.level = level_keys[self._log_level.currentIndex()]

            settings_mgr.save()
            settings_mgr.apply_runtime_settings()

            main_win = self.window()
            if hasattr(main_win, "apply_general_settings"):
                main_win.apply_general_settings()
            self._refresh_function_pages(main_win)

            logger.info("设置已保存")
            show_success(
                self.window(),
                "设置已保存",
                "日志级别与线程数已立即生效；DPI/输出目录等将在各功能页下次使用时应用",
            )
        except Exception as e:
            logger.exception(f"保存设置失败: {e}")
            show_error(self.window(), "保存失败", str(e))

    def _reset(self):
        reply = QMessageBox.question(
            self.window(),
            "确认重置",
            "是否将所有设置恢复为默认值？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        settings_mgr.reset_to_defaults()
        self._load_from_settings()
        settings_mgr.apply_runtime_settings()
        main_win = self.window()
        if hasattr(main_win, "apply_general_settings"):
            main_win.apply_general_settings()
        self._refresh_function_pages(main_win)
        show_info(self.window(), "已恢复默认设置", "界面选项已刷新")

    def _refresh_function_pages(self, main_win) -> None:
        """保存/重置后刷新各功能页的默认控件值"""
        for attr in (
            "split_page",
            "ocr_page",
            "image_page",
            "web_page",
            "compress_page",
        ):
            page = getattr(main_win, attr, None)
            if page is not None and hasattr(page, "_apply_setting_defaults"):
                try:
                    page._apply_setting_defaults()
                except Exception as e:
                    logger.warning(f"刷新 {attr} 默认设置失败: {e}")
