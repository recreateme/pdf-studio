"""
PDF Studio - 网页转PDF页面
支持单URL/批量URL，懒加载，阅读模式，Cookie
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QTextEdit, QSplitter,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    LineEdit, CheckBox, SpinBox,
    StrongBodyLabel, FluentIcon, TextEdit,
    DoubleSpinBox, ToolButton,
)

from app.widgets.combo_box import StudioComboBox
from app.widgets.common import (
    TaskProgressCard, show_success, show_error,
    show_warning, show_info,
)
from app.workers.base_worker import WebToPDFWorker, WebToImageWorker, submit_worker
from app.config.settings import settings_mgr
from app.utils.helpers import open_in_explorer, safe_filename
from app.utils.logger import logger
from core.web.processor import WebToPDFOptions, WebToImageOptions


class WebPage(QWidget):
    """网页转PDF页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("webPage")
        self._current_worker = None
        self._setup_ui()
        self._check_playwright()
        self._apply_setting_defaults()

    def _apply_setting_defaults(self) -> None:
        ws = settings_mgr.web
        self._timeout_spin.setValue(ws.wait_timeout)
        idx = self._format_combo.findText(ws.page_format)
        if idx >= 0:
            self._format_combo.setCurrentIndex(idx)
        self._scroll_spin.setValue(ws.max_scroll_times)
        self._wait_spin.setValue(max(ws.scroll_wait, 0.1))
        margin = int(ws.margin_top)
        self._margin_spin.setValue(margin)
        self._bg_cb.setChecked(ws.print_background)
        self._js_cb.setChecked(ws.enable_javascript)
        if settings_mgr.pdf.default_output_dir:
            self._output_dir_edit.setText(settings_mgr.pdf.default_output_dir)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("网页转 PDF / 截图"))
        root.addWidget(CaptionLabel("内置 Chromium · 支持懒加载 · 阅读模式 · Cookie · 长页截图"))

        self._playwright_status = CaptionLabel("")
        root.addWidget(self._playwright_status)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([420, 540])
        root.addWidget(splitter, 1)

        self._progress_card = TaskProgressCard("准备就绪")
        self._progress_card.setVisible(False)
        self._progress_card.cancelRequested.connect(self._cancel)
        root.addWidget(self._progress_card)

    def _build_left(self) -> QWidget:
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(480)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)
        scroll.setWidget(container)

        # URL 输入
        url_card = CardWidget()
        url_layout = QVBoxLayout(url_card)
        url_layout.setContentsMargins(16, 14, 16, 14)
        url_layout.setSpacing(10)
        url_layout.addWidget(StrongBodyLabel("URL 输入"))

        url_row = QHBoxLayout()
        self._url_edit = LineEdit()
        self._url_edit.setPlaceholderText("https://example.com")
        url_row.addWidget(self._url_edit, 1)
        url_layout.addLayout(url_row)

        url_layout.addWidget(CaptionLabel("批量模式（每行一个URL）："))
        self._batch_edit = TextEdit()
        self._batch_edit.setFixedHeight(100)
        self._batch_edit.setPlaceholderText("每行输入一个URL\nhttps://example.com\nhttps://another.com")
        url_layout.addWidget(self._batch_edit)

        import_batch_btn = PushButton("从TXT/CSV导入URL")
        import_batch_btn.clicked.connect(self._import_urls)
        url_layout.addWidget(import_batch_btn)
        layout.addWidget(url_card)

        # 加载设置
        load_card = CardWidget()
        load_layout = QVBoxLayout(load_card)
        load_layout.setContentsMargins(16, 14, 16, 14)
        load_layout.setSpacing(10)
        load_layout.addWidget(StrongBodyLabel("页面加载设置"))

        timeout_row = QHBoxLayout()
        timeout_row.addWidget(CaptionLabel("超时时间（秒）："))
        self._timeout_spin = SpinBox()
        self._timeout_spin.setRange(5, 300)
        self._timeout_spin.setValue(30)
        timeout_row.addWidget(self._timeout_spin)
        timeout_row.addStretch()
        load_layout.addLayout(timeout_row)

        wait_row = QHBoxLayout()
        wait_row.addWidget(CaptionLabel("加载后等待（秒）："))
        self._wait_spin = DoubleSpinBox()
        self._wait_spin.setRange(0, 30)
        self._wait_spin.setValue(2.0)
        self._wait_spin.setSingleStep(0.5)
        wait_row.addWidget(self._wait_spin)
        wait_row.addStretch()
        load_layout.addLayout(wait_row)

        self._scroll_cb = CheckBox("滚动到底部（触发懒加载）")
        self._scroll_cb.setChecked(True)
        load_layout.addWidget(self._scroll_cb)

        scroll_row = QHBoxLayout()
        scroll_row.addWidget(CaptionLabel("最大滚动次数："))
        self._scroll_spin = SpinBox()
        self._scroll_spin.setRange(1, 100)
        self._scroll_spin.setValue(20)
        scroll_row.addWidget(self._scroll_spin)
        scroll_row.addStretch()
        load_layout.addLayout(scroll_row)

        self._js_cb = CheckBox("执行JavaScript")
        self._js_cb.setChecked(True)
        load_layout.addWidget(self._js_cb)

        self._reading_mode_cb = CheckBox("阅读模式（移除广告/导航栏）")
        load_layout.addWidget(self._reading_mode_cb)

        layout.addWidget(load_card)

        # PDF设置
        pdf_card = CardWidget()
        pdf_layout = QVBoxLayout(pdf_card)
        pdf_layout.setContentsMargins(16, 14, 16, 14)
        pdf_layout.setSpacing(10)
        pdf_layout.addWidget(StrongBodyLabel("PDF 输出设置"))

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(CaptionLabel("页面格式："))
        self._format_combo = StudioComboBox()
        self._format_combo.addItems(["A4", "A3", "Letter", "Legal"])
        fmt_row.addWidget(self._format_combo)
        fmt_row.addStretch()
        pdf_layout.addLayout(fmt_row)

        margin_row = QHBoxLayout()
        margin_row.addWidget(CaptionLabel("页边距（mm）："))
        self._margin_spin = SpinBox()
        self._margin_spin.setRange(0, 50)
        self._margin_spin.setValue(10)
        margin_row.addWidget(self._margin_spin)
        margin_row.addStretch()
        pdf_layout.addLayout(margin_row)

        self._bg_cb = CheckBox("打印背景色/图片")
        self._bg_cb.setChecked(True)
        pdf_layout.addWidget(self._bg_cb)

        layout.addWidget(pdf_card)

        # 截图设置
        shot_card = CardWidget()
        shot_layout = QVBoxLayout(shot_card)
        shot_layout.setContentsMargins(16, 14, 16, 14)
        shot_layout.setSpacing(10)
        shot_layout.addWidget(StrongBodyLabel("网页截图设置"))

        shot_fmt_row = QHBoxLayout()
        shot_fmt_row.addWidget(CaptionLabel("图片格式："))
        self._shot_format_combo = StudioComboBox()
        self._shot_format_combo.addItems(["PNG", "JPEG"])
        shot_fmt_row.addWidget(self._shot_format_combo)
        shot_fmt_row.addStretch()
        shot_layout.addLayout(shot_fmt_row)

        self._shot_full_cb = CheckBox("整页长截图")
        self._shot_full_cb.setChecked(True)
        shot_layout.addWidget(self._shot_full_cb)

        vp_row = QHBoxLayout()
        vp_row.addWidget(CaptionLabel("视口宽×高："))
        self._shot_vp_w = SpinBox()
        self._shot_vp_w.setRange(320, 3840)
        self._shot_vp_w.setValue(1280)
        self._shot_vp_h = SpinBox()
        self._shot_vp_h.setRange(240, 2160)
        self._shot_vp_h.setValue(900)
        vp_row.addWidget(self._shot_vp_w)
        vp_row.addWidget(CaptionLabel("×"))
        vp_row.addWidget(self._shot_vp_h)
        vp_row.addStretch()
        shot_layout.addLayout(vp_row)

        layout.addWidget(shot_card)

        # Cookie 设置
        cookie_card = CardWidget()
        ck_layout = QVBoxLayout(cookie_card)
        ck_layout.setContentsMargins(16, 14, 16, 14)
        ck_layout.setSpacing(10)
        ck_layout.addWidget(StrongBodyLabel("登录态 / Cookie（可选）"))
        ck_layout.addWidget(CaptionLabel("导入浏览器导出的JSON格式Cookie文件"))

        ck_row = QHBoxLayout()
        self._cookie_edit = LineEdit()
        self._cookie_edit.setPlaceholderText("Cookie JSON 文件路径（可选）")
        ck_browse = PushButton("浏览")
        ck_browse.clicked.connect(self._browse_cookie)
        ck_row.addWidget(self._cookie_edit, 1)
        ck_row.addWidget(ck_browse)
        ck_layout.addLayout(ck_row)
        layout.addWidget(cookie_card)

        # 输出目录
        out_card = CardWidget()
        out_layout = QVBoxLayout(out_card)
        out_layout.setContentsMargins(16, 14, 16, 14)
        out_layout.setSpacing(10)
        out_layout.addWidget(StrongBodyLabel("输出设置"))

        out_row = QHBoxLayout()
        self._output_dir_edit = LineEdit()
        self._output_dir_edit.setPlaceholderText("输出目录")
        out_browse = PushButton("浏览")
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._output_dir_edit, 1)
        out_row.addWidget(out_browse)
        out_layout.addLayout(out_row)
        layout.addWidget(out_card)

        # 执行按钮
        btn_row = QHBoxLayout()
        self._convert_btn = PrimaryPushButton(FluentIcon.GLOBE, "转 PDF")
        self._convert_btn.setFixedHeight(40)
        self._convert_btn.clicked.connect(self._start_convert)
        self._screenshot_btn = PushButton(FluentIcon.PHOTO, "网页截图")
        self._screenshot_btn.setFixedHeight(40)
        self._screenshot_btn.clicked.connect(self._start_screenshot)
        btn_row.addWidget(self._convert_btn, 1)
        btn_row.addWidget(self._screenshot_btn, 1)
        layout.addLayout(btn_row)

        layout.addStretch()
        return scroll

    def _build_right(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel("操作日志"))

        self._log_edit = TextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setPlaceholderText("转换日志将显示在此处...")
        layout.addWidget(self._log_edit, 1)

        clear_btn = PushButton("清空日志")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._log_edit.clear)
        layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return panel

    # ─────────────────────────────────────────
    # Playwright 检查
    # ─────────────────────────────────────────

    def _check_playwright(self):
        try:
            import playwright
            self._playwright_status.setText("✓ Playwright 已安装")
            self._playwright_status.setStyleSheet("color: #107C10;")
        except ImportError:
            self._playwright_status.setText(
                "⚠ Playwright 未安装  请运行：pip install playwright && playwright install chromium"
            )
            self._playwright_status.setStyleSheet("color: #FF8C00;")
            self._convert_btn.setEnabled(False)
            self._screenshot_btn.setEnabled(False)

    # ─────────────────────────────────────────
    # 操作
    # ─────────────────────────────────────────

    def _import_urls(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择URL文件", "", "文本文件 (*.txt *.csv)"
        )
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8")
                self._batch_edit.setPlainText(text.strip())
            except Exception as e:
                show_error(self, "导入失败", str(e))

    def _browse_cookie(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择Cookie文件", "", "JSON 文件 (*.json)"
        )
        if path:
            self._cookie_edit.setText(path)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._output_dir_edit.setText(d)

    def _get_urls(self) -> list[str]:
        urls = []
        single = self._url_edit.text().strip()
        if single:
            urls.append(single)
        batch_text = self._batch_edit.toPlainText().strip()
        if batch_text:
            for line in batch_text.splitlines():
                line = line.strip()
                if line and line.startswith("http"):
                    urls.append(line)
        return list(dict.fromkeys(urls))  # 去重保序

    def _start_screenshot(self):
        urls = self._get_urls()
        if not urls:
            show_warning(self, "请输入至少一个URL")
            return

        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            show_warning(self, "请设置输出目录")
            return

        if len(urls) == 1:
            self._screenshot_single(urls[0], output_dir)
        else:
            self._batch_screenshot(urls, output_dir)

    def _screenshot_options(self, out_path: Path):
        fmt = self._shot_format_combo.currentText()
        return WebToImageOptions(
            output_path=out_path,
            full_page=self._shot_full_cb.isChecked(),
            format=fmt,
            viewport_width=self._shot_vp_w.value(),
            viewport_height=self._shot_vp_h.value(),
            wait_timeout=self._timeout_spin.value(),
            scroll_to_bottom=self._scroll_cb.isChecked(),
            max_scroll_times=self._scroll_spin.value(),
        )

    def _screenshot_single(self, url: str, output_dir: str) -> None:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        name = safe_filename(f"{parsed.netloc}{parsed.path}")[:60] or "screenshot"
        fmt = self._shot_format_combo.currentText()
        ext = "jpg" if fmt == "JPEG" else "png"
        out_path = Path(output_dir) / f"{name}.{ext}"

        self._convert_btn.setEnabled(False)
        self._screenshot_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._log_edit.clear()

        worker = WebToImageWorker(url, self._screenshot_options(out_path))
        self._current_worker = worker
        worker.signals.message.connect(self._on_log_message)
        worker.signals.finished.connect(self._on_screenshot_done)
        worker.signals.error.connect(self._on_convert_error)
        worker.signals.cancelled.connect(
            lambda: (
                self._progress_card.set_cancelled(),
                self._convert_btn.setEnabled(True),
                self._screenshot_btn.setEnabled(True),
                self._log_edit.append("✗ 已取消：网页截图"),
            )
        )
        submit_worker(worker)

    def _batch_screenshot(self, urls: list[str], output_dir: str) -> None:
        from app.workers.base_worker import BaseWorker
        from core.web.processor import WebProcessor
        from urllib.parse import urlparse

        class BatchScreenshotWorker(BaseWorker):
            def __init__(self_, urls, output_dir, options_factory, image_format):
                super().__init__()
                self_.urls = urls
                self_.output_dir = Path(output_dir)
                self_.options_factory = options_factory
                self_.image_format = image_format

            def run_task(self_):
                processor = WebProcessor()
                results = []
                ext = "jpg" if self_.image_format == "JPEG" else "png"
                for idx, url in enumerate(self_.urls):
                    if self_.is_cancelled():
                        break
                    parsed = urlparse(url)
                    name = safe_filename(f"{parsed.netloc}{parsed.path}")[:60] or f"shot_{idx+1}"
                    out_path = self_.output_dir / f"{name}.{ext}"
                    opts = self_.options_factory(out_path)
                    self_.emit_message(f"[{idx+1}/{len(self_.urls)}] {url}")
                    try:
                        p = processor.url_to_screenshot(
                            url, opts, progress_cb=self_.emit_message
                        )
                        results.append((url, str(p)))
                    except Exception as e:
                        results.append((url, f"失败: {e}"))
                    self_.emit_progress(idx + 1, len(self_.urls))
                return results

        self._convert_btn.setEnabled(False)
        self._screenshot_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._log_edit.clear()
        self._log_edit.append(f"批量截图：{len(urls)} 个 URL")

        worker = BatchScreenshotWorker(
            urls, output_dir, self._screenshot_options,
            self._shot_format_combo.currentText(),
        )
        self._current_worker = worker
        worker.signals.progress.connect(self._progress_card.update_progress)
        worker.signals.message.connect(self._on_log_message)
        worker.signals.finished.connect(self._on_batch_screenshot_done)
        worker.signals.error.connect(self._on_convert_error)
        worker.signals.cancelled.connect(
            lambda: (
                self._progress_card.set_cancelled(),
                self._convert_btn.setEnabled(True),
                self._screenshot_btn.setEnabled(True),
                self._log_edit.append("✗ 已取消：批量截图"),
            )
        )
        submit_worker(worker)

    def _on_screenshot_done(self, output_path):
        self._convert_btn.setEnabled(True)
        self._screenshot_btn.setEnabled(True)
        self._progress_card.set_finished(True)
        self._log_edit.append(f"✓ 截图完成：{output_path}")
        show_success(self, "截图完成", str(Path(str(output_path)).name))
        open_in_explorer(output_path)

    def _on_batch_screenshot_done(self, results: list):
        self._convert_btn.setEnabled(True)
        self._screenshot_btn.setEnabled(True)
        ok = sum(1 for _, r in results if not str(r).startswith("失败"))
        self._progress_card.set_finished(True, f"完成 {ok}/{len(results)}")
        for url, result in results:
            self._log_edit.append(f"{'✓' if not str(result).startswith('失败') else '✗'} {url}")
        show_success(self, "批量截图完成", f"{ok}/{len(results)} 成功")
        if ok > 0:
            open_in_explorer(self._output_dir_edit.text())

    def _start_convert(self):
        urls = self._get_urls()
        if not urls:
            show_warning(self, "请输入至少一个URL")
            return

        output_dir = self._output_dir_edit.text().strip()
        if not output_dir:
            show_warning(self, "请设置输出目录")
            return

        margin = float(self._margin_spin.value())
        cookie = self._cookie_edit.text().strip() or None

        self._convert_btn.setEnabled(False)
        self._screenshot_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._log_edit.clear()

        if len(urls) == 1:
            # 单URL模式
            from urllib.parse import urlparse
            from app.utils.helpers import safe_filename
            parsed = urlparse(urls[0])
            name = safe_filename(f"{parsed.netloc}{parsed.path}")[:60] or "output"
            out_path = Path(output_dir) / f"{name}.pdf"

            options = WebToPDFOptions(
                output_path=out_path,
                wait_timeout=self._timeout_spin.value(),
                wait_after_load=self._wait_spin.value(),
                scroll_to_bottom=self._scroll_cb.isChecked(),
                max_scroll_times=self._scroll_spin.value(),
                page_format=self._format_combo.currentText(),
                margin_top=margin, margin_bottom=margin,
                margin_left=margin, margin_right=margin,
                print_background=self._bg_cb.isChecked(),
                enable_javascript=self._js_cb.isChecked(),
                reading_mode=self._reading_mode_cb.isChecked(),
                cookie_file=Path(cookie) if cookie else None,
            )

            worker = WebToPDFWorker(urls[0], options)
            self._current_worker = worker
            worker.signals.message.connect(self._on_log_message)
            worker.signals.finished.connect(self._on_convert_done)
            worker.signals.error.connect(self._on_convert_error)
            worker.signals.cancelled.connect(
                lambda: (
                    self._progress_card.set_cancelled(),
                    self._convert_btn.setEnabled(True),
                    self._screenshot_btn.setEnabled(True),
                    self._log_edit.append("✗ 已取消：单 URL转换"),
                )
            )
            submit_worker(worker)
        else:
            # 批量模式
            self._log_edit.append(f"批量模式：{len(urls)} 个URL")
            self._batch_convert(urls, output_dir, margin, cookie)

    def _batch_convert(self, urls, output_dir, margin, cookie):
        """批量转换（Worker 内调用 WebProcessor，支持有限并行）"""
        from app.workers.base_worker import BaseWorker
        from core.web.processor import WebProcessor, WebToPDFOptions
        from pathlib import Path

        common_settings = {
            "wait_timeout": self._timeout_spin.value(),
            "wait_after_load": self._wait_spin.value(),
            "scroll_to_bottom": self._scroll_cb.isChecked(),
            "max_scroll_times": self._scroll_spin.value(),
            "page_format": self._format_combo.currentText(),
            "print_background": self._bg_cb.isChecked(),
            "enable_javascript": self._js_cb.isChecked(),
            "reading_mode": self._reading_mode_cb.isChecked(),
            "cookie_file": Path(cookie) if cookie else None,
        }

        class BatchWebWorker(BaseWorker):
            def __init__(self_, urls, output_dir, margin, common_settings):
                super().__init__()
                self_.urls = urls
                self_.output_dir = Path(output_dir)
                self_.margin = margin
                self_.common = common_settings

            def run_task(self_):
                processor = WebProcessor()
                base = WebToPDFOptions(
                    output_path=self_.output_dir / "_placeholder.pdf",
                    margin_top=self_.margin,
                    margin_bottom=self_.margin,
                    margin_left=self_.margin,
                    margin_right=self_.margin,
                    wait_timeout=self_.common["wait_timeout"],
                    wait_after_load=self_.common["wait_after_load"],
                    scroll_to_bottom=self_.common["scroll_to_bottom"],
                    max_scroll_times=self_.common["max_scroll_times"],
                    page_format=self_.common["page_format"],
                    print_background=self_.common["print_background"],
                    enable_javascript=self_.common["enable_javascript"],
                    reading_mode=self_.common["reading_mode"],
                    cookie_file=self_.common["cookie_file"],
                )

                def on_progress(cur, total, url):
                    self_.emit_message(f"[{cur}/{total}] {url}")
                    self_.emit_progress(cur, total)

                raw = processor.batch_urls_to_pdf(
                    self_.urls,
                    self_.output_dir,
                    base,
                    progress_cb=on_progress,
                    should_cancel=self_.is_cancelled,
                )
                formatted = []
                for url, outcome in raw:
                    if isinstance(outcome, Exception):
                        formatted.append((url, f"失败: {outcome}"))
                    else:
                        formatted.append((url, str(outcome)))
                return formatted

        worker = BatchWebWorker(urls, output_dir, margin, common_settings)
        self._current_worker = worker
        worker.signals.progress.connect(self._progress_card.update_progress)
        worker.signals.message.connect(self._on_log_message)
        worker.signals.finished.connect(self._on_batch_done)
        worker.signals.error.connect(self._on_convert_error)
        worker.signals.cancelled.connect(
            lambda: (
                self._progress_card.set_cancelled(),
                self._convert_btn.setEnabled(True),
                self._screenshot_btn.setEnabled(True),
                self._log_edit.append("✗ 已取消：批量转换"),
            )
        )
        submit_worker(worker)

    def _on_log_message(self, msg: str):
        self._log_edit.append(msg)
        self._progress_card.set_message(msg)

    def _on_convert_done(self, output_path):
        self._convert_btn.setEnabled(True)
        self._screenshot_btn.setEnabled(True)
        self._progress_card.set_finished(True)
        self._log_edit.append(f"✓ 完成：{output_path}")
        show_success(self, "转换完成", str(Path(str(output_path)).name))
        open_in_explorer(output_path)

    def _on_batch_done(self, results: list):
        self._convert_btn.setEnabled(True)
        self._screenshot_btn.setEnabled(True)
        ok = sum(1 for _, r in results if not str(r).startswith("失败"))
        self._progress_card.set_finished(True, f"完成 {ok}/{len(results)}")
        for url, result in results:
            self._log_edit.append(f"{'✓' if not str(result).startswith('失败') else '✗'} {url}")
        show_success(self, "批量转换完成", f"{ok}/{len(results)} 成功")

    def _on_convert_error(self, msg: str):
        self._convert_btn.setEnabled(True)
        self._screenshot_btn.setEnabled(True)
        self._progress_card.set_finished(False, msg)
        self._log_edit.append(f"✗ 错误：{msg}")
        show_error(self, "转换失败", msg)

    def _cancel(self):
        if self._current_worker:
            self._current_worker.request_cancel()
            self._convert_btn.setEnabled(True)
            self._screenshot_btn.setEnabled(True)
