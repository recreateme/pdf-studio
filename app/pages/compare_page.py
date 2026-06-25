"""
PDF Studio - PDF 对比页面
轻量对比：页数、体积、元数据、逐页文本/渲染抽样
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSplitter
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, StrongBodyLabel, FluentIcon,
    LineEdit, BodyLabel, TextEdit, PasswordLineEdit,
)

from app.widgets.common import (
    DropZone, TaskProgressCard, show_success, show_error, show_warning,
    wps_hint_label,
)
from app.workers.base_worker import BaseWorker, submit_worker
from core.pdf.compare import PDFCompareOptions, PDFCompareResult


class PDFCompareWorker(BaseWorker):
    """PDF 对比 Worker"""

    def __init__(
        self,
        path_a: str,
        path_b: str,
        password_a: str = "",
        password_b: str = "",
    ) -> None:
        super().__init__()
        self.path_a = path_a
        self.path_b = path_b
        self.password_a = password_a
        self.password_b = password_b
        self.task_label = "PDF 对比"

    def run_task(self):
        from core.pdf.compare import PDFCompareService

        def progress_cb(current: int, total: int) -> None:
            self.emit_progress(current, total)
            self.emit_message(f"对比第 {current}/{total} 页")

        return PDFCompareService().compare(
            self.path_a,
            self.path_b,
            self.password_a,
            self.password_b,
            options=PDFCompareOptions(),
            progress_cb=progress_cb,
            should_cancel=self.is_cancelled,
        )


class ComparePage(ScrollArea):
    """PDF 轻量对比"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("comparePage")
        self._path_a: Optional[str] = None
        self._path_b: Optional[str] = None
        self._current_worker: Optional[PDFCompareWorker] = None
        self._last_result: Optional[PDFCompareResult] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("PDF 对比"))
        root.addWidget(wps_hint_label("compare"))
        root.addWidget(CaptionLabel("并排比较两个 PDF 的差异，适合版本核对与批量质检"))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([420, 520])
        root.addWidget(splitter, 1)

        self._progress = TaskProgressCard("准备就绪")
        self._progress.setVisible(False)
        self._progress.cancelRequested.connect(self._cancel)
        root.addWidget(self._progress)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(16)

        drop = DropZone("pdf", "拖放两个 PDF 到此处（先 A 后 B）")
        drop.filesDropped.connect(self._on_dropped)
        layout.addWidget(drop)

        for side, title in (("a", "文件 A"), ("b", "文件 B")):
            card = CardWidget()
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(16, 14, 16, 14)
            card_l.setSpacing(8)
            card_l.addWidget(StrongBodyLabel(title))

            path_row = QHBoxLayout()
            edit = LineEdit()
            edit.setPlaceholderText("选择 PDF 文件…")
            setattr(self, f"_path_{side}_edit", edit)
            browse = PushButton("浏览")
            browse.clicked.connect(lambda _, s=side: self._browse(s))
            path_row.addWidget(edit, 1)
            path_row.addWidget(browse)
            card_l.addLayout(path_row)

            pwd_row = QHBoxLayout()
            pwd_row.addWidget(CaptionLabel("打开密码（可选）："))
            pwd_edit = PasswordLineEdit()
            pwd_edit.setPlaceholderText("加密 PDF 需填写")
            pwd_edit.setClearButtonEnabled(True)
            setattr(self, f"_pwd_{side}_edit", pwd_edit)
            pwd_row.addWidget(pwd_edit, 1)
            card_l.addLayout(pwd_row)
            layout.addWidget(card)

        hint = BodyLabel(
            "对比内容：\n"
            "· 页数、体积、文档元数据\n"
            "· 重叠页文本（空白页时低 DPI 渲染抽样）\n"
            "· 不含像素级全页渲染 diff"
        )
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        self._run_btn = PrimaryPushButton(FluentIcon.VIEW, "开始对比")
        self._run_btn.setFixedHeight(40)
        self._run_btn.clicked.connect(self._run)
        self._export_btn = PushButton(FluentIcon.SAVE, "导出报告")
        self._export_btn.setFixedHeight(40)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_report)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()
        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(StrongBodyLabel("对比结果"))
        self._result = TextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText("对比报告将显示在此处…")
        layout.addWidget(self._result, 1)
        return panel

    def _on_dropped(self, files: list[str]) -> None:
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        if not pdfs:
            show_warning(self, "请拖入 PDF 文件")
            return
        if len(pdfs) >= 1:
            self._set_path("a", pdfs[0])
        if len(pdfs) >= 2:
            self._set_path("b", pdfs[1])

    def _set_path(self, side: str, path: str) -> None:
        if side == "a":
            self._path_a = path
            self._path_a_edit.setText(path)
        else:
            self._path_b = path
            self._path_b_edit.setText(path)

    def _browse(self, which: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF", "", "PDF (*.pdf)")
        if path:
            self._set_path(which, path)

    def _run(self) -> None:
        path_a = self._path_a_edit.text().strip() or self._path_a
        path_b = self._path_b_edit.text().strip() or self._path_b
        if not path_a or not path_b:
            show_warning(self, "请选择两个 PDF 文件")
            return
        if not Path(path_a).exists() or not Path(path_b).exists():
            show_error(self, "文件不存在", "请检查文件路径")
            return
        if Path(path_a).resolve() == Path(path_b).resolve():
            show_warning(self, "请选择两个不同的文件", "同一文件对比无意义")
            return

        pwd_a = self._pwd_a_edit.text()
        pwd_b = self._pwd_b_edit.text()

        self._run_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.set_message("")
        self._progress.set_status("对比中…", "#0078D4")
        self._progress._cancel_btn.setEnabled(True)
        self._result.clear()
        self._last_result = None

        worker = PDFCompareWorker(path_a, path_b, pwd_a, pwd_b)
        self._current_worker = worker
        worker.signals.progress.connect(self._progress.update_progress)
        worker.signals.message.connect(self._progress.set_message)
        worker.signals.finished.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(self._on_cancelled)

        if not submit_worker(worker, "PDF 对比"):
            self._run_btn.setEnabled(True)
            self._progress.setVisible(False)
            self._current_worker = None

    def _cancel(self) -> None:
        if self._current_worker:
            self._current_worker.request_cancel()

    def _on_done(self, result: PDFCompareResult) -> None:
        self._current_worker = None
        self._run_btn.setEnabled(True)
        self._last_result = result
        self._export_btn.setEnabled(True)
        self._progress.set_finished(True)

        lines = result.summary_lines()
        self._result.setPlainText("\n".join(lines))

        if result.cancelled:
            show_warning(self, "对比已取消", "已生成部分页的对比结果")
        elif result.is_mostly_match and result.metadata_match:
            show_success(self, "对比完成", "两个 PDF 基本一致")
        else:
            show_warning(self, "对比完成", "发现差异，请查看报告")

    def _on_error(self, msg: str) -> None:
        self._current_worker = None
        self._run_btn.setEnabled(True)
        self._export_btn.setEnabled(False)
        self._progress.set_finished(False, msg)
        show_error(self, "对比失败", msg)

    def _on_cancelled(self) -> None:
        self._current_worker = None
        self._run_btn.setEnabled(True)
        self._progress.set_cancelled()

    def _export_report(self) -> None:
        if not self._last_result:
            show_warning(self, "暂无报告", "请先完成一次对比")
            return
        default_name = (
            f"compare_{self._last_result.path_a.stem}_vs_"
            f"{self._last_result.path_b.stem}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出对比报告", default_name, "文本 (*.txt)"
        )
        if not path:
            return
        report = "\n".join(self._last_result.summary_lines())
        Path(path).write_text(report, encoding="utf-8")
        show_success(self, "报告已导出", path)
