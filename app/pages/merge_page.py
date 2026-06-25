"""
PDF Studio - PDF 合并页面
支持拖拽排序、重复检测、书签生成、页面尺寸统一
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFileDialog, QListWidget,
    QListWidgetItem, QAbstractItemView, QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    LineEdit, CheckBox, SubtitleLabel,
    StrongBodyLabel, FluentIcon, InfoBar,
    ProgressBar, ToolButton,
)

from app.widgets.combo_box import StudioComboBox
from app.widgets.list_styles import apply_list_widget_style
from app.widgets.common import (
    DropZone, TaskProgressCard, FileListItem,
    show_success, show_error, show_warning, show_info,
    wps_hint_label, finish_output_task,
)
from app.workers.base_worker import PDFMergeWorker, submit_worker
from app.config.settings import settings_mgr
from app.utils.helpers import get_file_size_str, open_in_explorer, collect_files
from app.utils.logger import logger
from core.pdf.processor import MergeOptions, PDFMerger as PDFMergerEngine


class MergeFileList(QWidget):
    """带拖拽排序的文件列表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 使用QListWidget支持拖拽排序
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        apply_list_widget_style(self._list)
        layout.addWidget(self._list, 1)

        # 操作栏
        btn_row = QHBoxLayout()
        self._count_label = CaptionLabel("共 0 个文件")

        up_btn = ToolButton(FluentIcon.UP)
        up_btn.setToolTip("上移")
        up_btn.clicked.connect(self._move_up)

        down_btn = ToolButton(FluentIcon.DOWN)
        down_btn.setToolTip("下移")
        down_btn.clicked.connect(self._move_down)

        del_btn = ToolButton(FluentIcon.DELETE)
        del_btn.setToolTip("删除选中")
        del_btn.clicked.connect(self._delete_selected)

        clear_btn = PushButton("清空")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self.clear)

        btn_row.addWidget(self._count_label)
        btn_row.addStretch()
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def add_files(self, paths: list[str]) -> int:
        """添加文件，返回实际添加数量（跳过已存在的）"""
        existing = set(self.get_paths())
        added = 0
        for p in paths:
            if p not in existing and Path(p).exists():
                item = QListWidgetItem(f"  {Path(p).name}  [{get_file_size_str(p)}]")
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                self._list.addItem(item)
                existing.add(p)
                added += 1
        self._update_count()
        return added

    def get_paths(self) -> list[str]:
        """从列表控件读取路径，过滤无效项（与拖拽顺序保持一致）"""
        paths: list[str] = []
        seen: set[str] = set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            p = item.data(Qt.ItemDataRole.UserRole)
            if not p or not isinstance(p, str):
                continue
            p = str(p)
            if not Path(p).exists():
                continue
            if p in seen:
                continue
            seen.add(p)
            paths.append(p)
        return paths

    def validate(self) -> tuple[list[str], list[str]]:
        """返回 (有效路径, 无效条目提示)"""
        valid: list[str] = []
        issues: list[str] = []
        seen: set[str] = set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.text() if item else f"第{i + 1}项"
            p = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not p:
                issues.append(f"{name}：缺少文件路径")
                continue
            p = str(p)
            if not Path(p).exists():
                issues.append(f"{name}：文件不存在")
                continue
            if p in seen:
                issues.append(f"{Path(p).name}：重复条目")
                continue
            seen.add(p)
            valid.append(p)
        return valid, issues

    def clear(self):
        self._list.clear()
        self._update_count()

    def _move_up(self):
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)

    def _delete_selected(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._update_count()

    def _update_count(self):
        n = self._list.count()
        self._count_label.setText(f"共 {n} 个文件")

    def count(self) -> int:
        return self._list.count()


class MergePage(ScrollArea):
    """PDF 合并页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mergePage")
        self._current_worker: Optional[PDFMergeWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("PDF 合并"))
        root.addWidget(wps_hint_label("merge"))
        root.addWidget(CaptionLabel("将多个PDF文件按顺序合并为一个，支持自动书签生成"))

        # ── 文件导入 ───────────────────────────
        import_card = CardWidget()
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(16, 14, 16, 14)
        import_layout.setSpacing(10)

        import_layout.addWidget(StrongBodyLabel("导入文件"))

        # 按钮行
        btn_row = QHBoxLayout()
        add_file_btn = PrimaryPushButton(FluentIcon.DOCUMENT, "添加文件")
        add_file_btn.clicked.connect(self._add_files_dialog)
        add_folder_btn = PushButton(FluentIcon.FOLDER, "添加文件夹")
        add_folder_btn.clicked.connect(self._add_folder_dialog)
        dedup_btn = PushButton(FluentIcon.SEARCH, "检测重复")
        dedup_btn.clicked.connect(self._detect_duplicates)
        btn_row.addWidget(add_file_btn)
        btn_row.addWidget(add_folder_btn)
        btn_row.addWidget(dedup_btn)
        btn_row.addStretch()
        import_layout.addLayout(btn_row)

        # 拖放区
        drop_zone = DropZone(accept_types="pdf", hint_text="拖放PDF文件或文件夹到此处")
        drop_zone.filesDropped.connect(self._on_files_dropped)
        import_layout.addWidget(drop_zone)

        root.addWidget(import_card)

        # ── 文件列表 ───────────────────────────
        list_card = CardWidget()
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(16, 14, 16, 14)
        list_layout.setSpacing(8)

        list_layout.addWidget(StrongBodyLabel("合并顺序（可拖拽调整）"))
        self._file_list = MergeFileList()
        self._file_list.setMinimumHeight(240)
        list_layout.addWidget(self._file_list)

        root.addWidget(list_card)

        # ── 合并选项 ───────────────────────────
        options_card = CardWidget()
        opt_layout = QVBoxLayout(options_card)
        opt_layout.setContentsMargins(16, 14, 16, 14)
        opt_layout.setSpacing(12)

        opt_layout.addWidget(StrongBodyLabel("合并选项"))

        # 书签选项
        self._add_bookmarks_cb = CheckBox("自动添加书签（使用文件名）")
        self._add_bookmarks_cb.setChecked(True)
        opt_layout.addWidget(self._add_bookmarks_cb)

        # 压缩选项
        self._compress_cb = CheckBox("合并后压缩优化")
        opt_layout.addWidget(self._compress_cb)

        # 页面尺寸统一
        size_row = QHBoxLayout()
        size_row.addWidget(CaptionLabel("统一页面尺寸："))
        self._page_size_combo = StudioComboBox()
        self._page_size_combo.addItems(["不统一（保持原始）", "A4", "A3", "Letter"])
        size_row.addWidget(self._page_size_combo)
        size_row.addStretch()
        opt_layout.addLayout(size_row)

        root.addWidget(options_card)

        # ── 输出设置 ───────────────────────────
        output_card = CardWidget()
        out_layout = QVBoxLayout(output_card)
        out_layout.setContentsMargins(16, 14, 16, 14)
        out_layout.setSpacing(10)

        out_layout.addWidget(StrongBodyLabel("输出设置"))

        dir_row = QHBoxLayout()
        self._output_path_edit = LineEdit()
        self._output_path_edit.setPlaceholderText("输出文件路径（含文件名）")
        browse_btn = PushButton("浏览")
        browse_btn.clicked.connect(self._browse_output)
        dir_row.addWidget(self._output_path_edit, 1)
        dir_row.addWidget(browse_btn)
        out_layout.addLayout(dir_row)

        self._overwrite_cb = CheckBox("覆盖已存在的文件")
        out_layout.addWidget(self._overwrite_cb)

        root.addWidget(output_card)

        # ── 执行按钮 ───────────────────────────
        btn_row2 = QHBoxLayout()
        self._merge_btn = PrimaryPushButton(FluentIcon.ADD, "开始合并")
        self._merge_btn.setFixedHeight(40)
        self._merge_btn.clicked.connect(self._start_merge)
        btn_row2.addWidget(self._merge_btn, 1)
        root.addLayout(btn_row2)

        # 进度
        self._progress_card = TaskProgressCard("准备就绪")
        self._progress_card.setVisible(False)
        self._progress_card.cancelRequested.connect(self._cancel)
        root.addWidget(self._progress_card)

        root.addStretch()

    # ─────────────────────────────────────────
    # 文件操作
    # ─────────────────────────────────────────

    def _add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择PDF文件", "", "PDF 文件 (*.pdf)"
        )
        if files:
            added = self._file_list.add_files(files)
            show_info(self, f"已添加 {added} 个文件")

    def _add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            pdfs = collect_files(folder, {".pdf"}, recursive=True)
            added = self._file_list.add_files([str(p) for p in pdfs])
            show_info(self, f"已从文件夹添加 {added} 个PDF")

    def _on_files_dropped(self, paths: list[str]):
        # 支持文件夹拖拽
        all_pdfs = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                all_pdfs.extend(str(f) for f in collect_files(path, {".pdf"}))
            elif path.suffix.lower() == ".pdf":
                all_pdfs.append(p)
        if all_pdfs:
            added = self._file_list.add_files(all_pdfs)
            show_info(self, f"已添加 {added} 个文件")

    def _detect_duplicates(self):
        paths = self._file_list.get_paths()
        if len(paths) < 2:
            show_info(self, "文件不足", "至少需要2个文件才能检测重复")
            return
        try:
            merger = PDFMergerEngine()
            dups = merger.detect_duplicates(paths)
            if dups:
                msg = "\n".join(f"{Path(a).name} = {Path(b).name}" for a, b in dups[:5])
                show_warning(self, f"发现 {len(dups)} 对重复文件", msg)
            else:
                show_success(self, "未发现重复文件")
        except Exception as e:
            show_error(self, "检测失败", str(e))

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并PDF", "merged.pdf", "PDF 文件 (*.pdf)"
        )
        if path:
            if not path.endswith(".pdf"):
                path += ".pdf"
            self._output_path_edit.setText(path)

    # ─────────────────────────────────────────
    # 合并逻辑
    # ─────────────────────────────────────────

    def _start_merge(self):
        paths, issues = self._file_list.validate()
        if issues:
            show_warning(self, "列表存在问题", "\n".join(issues[:8]))
        if len(paths) < 2:
            show_warning(self, "文件不足", "请至少添加 2 个有效 PDF 文件")
            return

        output_path = self._output_path_edit.text().strip()
        if not output_path:
            show_warning(self, "请设置输出路径")
            return

        # 页面尺寸
        size_text = self._page_size_combo.currentText()
        unify = None if size_text.startswith("不") else size_text

        options = MergeOptions(
            output_path=Path(output_path),
            add_bookmarks=self._add_bookmarks_cb.isChecked(),
            unify_page_size=unify,
            compress_output=self._compress_cb.isChecked(),
            overwrite=self._overwrite_cb.isChecked(),
        )

        self._merge_btn.setEnabled(False)
        self._progress_card.setVisible(True)
        self._progress_card.set_status("合并中...", "#0078D4")

        worker = PDFMergeWorker(paths, options)
        self._current_worker = worker
        worker.signals.progress.connect(self._progress_card.update_progress)
        worker.signals.finished.connect(self._on_merge_done)
        worker.signals.error.connect(self._on_merge_error)
        worker.signals.cancelled.connect(lambda: self._progress_card.set_cancelled())
        submit_worker(worker)

    def _on_merge_done(self, output_path):
        self._merge_btn.setEnabled(True)
        self._progress_card.set_finished(True, str(output_path))
        finish_output_task(self, "合并完成", output_path)
        settings_mgr.add_recent_file(str(output_path))

    def _on_merge_error(self, msg: str):
        self._merge_btn.setEnabled(True)
        self._progress_card.set_finished(False, msg)
        show_error(self, "合并失败", msg)

    def _cancel(self):
        if self._current_worker:
            self._current_worker.request_cancel()
            self._merge_btn.setEnabled(True)
