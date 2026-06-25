"""
PDF Studio - 加密/解密页面
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTabWidget
from qfluentwidgets import (
    ScrollArea, CardWidget, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CheckBox,
    StrongBodyLabel, FluentIcon, LineEdit, PasswordLineEdit,
)
from app.widgets.common import DropZone, TaskProgressCard, show_success, show_error, show_warning, finish_output_task, wps_hint_label
from app.workers.base_worker import BaseWorker, submit_worker
from app.utils.helpers import open_in_explorer
from core.pdf.processor import PDFEncryptor


class EncryptPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("encryptPage")
        self._setup_ui()

    def _setup_ui(self):
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)
        root = QVBoxLayout(container)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(20)

        root.addWidget(TitleLabel("加密 / 解密"))
        root.addWidget(wps_hint_label("encrypt"))
        root.addWidget(CaptionLabel("为PDF添加密码保护或解除密码，支持权限控制"))

        tabs = QTabWidget()
        tabs.addTab(self._build_encrypt_tab(), "🔒 加密")
        tabs.addTab(self._build_decrypt_tab(), "🔓 解密")
        root.addWidget(tabs)
        root.addStretch()

    def _build_encrypt_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放要加密的PDF")
        drop.filesDropped.connect(lambda paths: self._set_enc_file(paths))
        layout.addWidget(drop)
        self._enc_file_label = CaptionLabel("")
        self._enc_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._enc_file_label)
        self._enc_path: Optional[str] = None

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)
        c_l.addWidget(StrongBodyLabel("密码设置"))
        c_l.addWidget(CaptionLabel("用户密码（打开文档需输入）："))
        self._user_pwd = PasswordLineEdit()
        self._user_pwd.setPlaceholderText("设置用户密码")
        c_l.addWidget(self._user_pwd)
        c_l.addWidget(CaptionLabel("所有者密码（可选，用于修改权限）："))
        self._owner_pwd = PasswordLineEdit()
        self._owner_pwd.setPlaceholderText("留空则与用户密码相同")
        c_l.addWidget(self._owner_pwd)

        c_l.addWidget(StrongBodyLabel("权限控制"))
        self._allow_print = CheckBox("允许打印")
        self._allow_print.setChecked(True)
        self._allow_copy = CheckBox("允许复制文字")
        self._allow_copy.setChecked(True)
        self._allow_edit = CheckBox("允许编辑")
        self._allow_edit.setChecked(False)
        c_l.addWidget(self._allow_print)
        c_l.addWidget(self._allow_copy)
        c_l.addWidget(self._allow_edit)

        out_row = QHBoxLayout()
        self._enc_out = LineEdit()
        self._enc_out.setPlaceholderText("加密后PDF路径")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._enc_out.setText(
            QFileDialog.getSaveFileName(self, "保存加密PDF", "encrypted.pdf", "PDF (*.pdf)")[0]
            or self._enc_out.text()
        ))
        out_row.addWidget(self._enc_out, 1)
        out_row.addWidget(browse)
        c_l.addLayout(out_row)
        layout.addWidget(card)

        btn = PrimaryPushButton(FluentIcon.FINGERPRINT, "加密PDF")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._encrypt)
        layout.addWidget(btn)

        self._enc_progress = TaskProgressCard("准备就绪")
        self._enc_progress.setVisible(False)
        layout.addWidget(self._enc_progress)
        layout.addStretch()
        return w

    def _build_decrypt_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        drop = DropZone("pdf", "拖放加密的PDF文件")
        drop.filesDropped.connect(lambda paths: self._set_dec_file(paths))
        layout.addWidget(drop)
        self._dec_file_label = CaptionLabel("")
        self._dec_file_label.setStyleSheet("color:#888;")
        layout.addWidget(self._dec_file_label)
        self._dec_path: Optional[str] = None

        card = CardWidget()
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(16, 14, 16, 14)
        c_l.setSpacing(10)
        c_l.addWidget(CaptionLabel("输入密码："))
        self._dec_pwd = PasswordLineEdit()
        self._dec_pwd.setPlaceholderText("输入PDF密码")
        c_l.addWidget(self._dec_pwd)

        out_row = QHBoxLayout()
        self._dec_out = LineEdit()
        self._dec_out.setPlaceholderText("解密后PDF路径")
        browse = PushButton("浏览")
        browse.clicked.connect(lambda: self._dec_out.setText(
            QFileDialog.getSaveFileName(self, "保存解密PDF", "decrypted.pdf", "PDF (*.pdf)")[0]
            or self._dec_out.text()
        ))
        out_row.addWidget(self._dec_out, 1)
        out_row.addWidget(browse)
        c_l.addLayout(out_row)
        layout.addWidget(card)

        btn = PrimaryPushButton(FluentIcon.FINGERPRINT, "解密PDF")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._decrypt)
        layout.addWidget(btn)

        self._dec_progress = TaskProgressCard("准备就绪")
        self._dec_progress.setVisible(False)
        layout.addWidget(self._dec_progress)
        layout.addStretch()
        return w

    def _set_enc_file(self, paths):
        if paths:
            self._enc_path = paths[0]
            self._enc_file_label.setText(Path(paths[0]).name)

    def _set_dec_file(self, paths):
        if paths:
            self._dec_path = paths[0]
            self._dec_file_label.setText(Path(paths[0]).name)

    def _encrypt(self):
        if not self._enc_path:
            show_warning(self, "请先导入PDF")
            return
        try:
            from app.utils.deps import ensure_pdf_encrypt_ready
            ensure_pdf_encrypt_ready()
        except RuntimeError as exc:
            show_error(self, "缺少加密依赖", str(exc))
            return
        pwd = self._user_pwd.text()
        if not pwd:
            show_warning(self, "请输入用户密码")
            return
        out = self._enc_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        self._enc_progress.setVisible(True)
        self._enc_progress.set_status("加密中...", "#0078D4")

        class EncWorker(BaseWorker):
            def __init__(self_, src, out, user_pwd, owner_pwd, allow_print, allow_copy, allow_edit):
                super().__init__()
                self_.src = src; self_.out = out
                self_.user_pwd = user_pwd; self_.owner_pwd = owner_pwd
                self_.allow_print = allow_print; self_.allow_copy = allow_copy; self_.allow_edit = allow_edit

            def run_task(self_):
                return PDFEncryptor().encrypt(
                    self_.src, self_.out, self_.user_pwd, self_.owner_pwd,
                    self_.allow_print, self_.allow_copy, self_.allow_edit,
                )

        w = EncWorker(
            self._enc_path, out, pwd,
            self._owner_pwd.text() or pwd,
            self._allow_print.isChecked(),
            self._allow_copy.isChecked(),
            self._allow_edit.isChecked(),
        )
        w.signals.finished.connect(lambda p: (
            self._enc_progress.set_finished(True),
            finish_output_task(self, "加密完成", p),
        ))
        w.signals.error.connect(lambda msg: (
            self._enc_progress.set_finished(False, msg),
            show_error(self, "加密失败", msg),
        ))
        submit_worker(w)

    def _decrypt(self):
        if not self._dec_path:
            show_warning(self, "请先导入加密PDF")
            return
        pwd = self._dec_pwd.text()
        if not pwd:
            show_warning(self, "请输入密码")
            return
        out = self._dec_out.text().strip()
        if not out:
            show_warning(self, "请设置输出路径")
            return

        self._dec_progress.setVisible(True)
        self._dec_progress.set_status("解密中...", "#0078D4")

        class DecWorker(BaseWorker):
            def __init__(self_, src, out, pwd):
                super().__init__()
                self_.src = src; self_.out = out; self_.pwd = pwd
            def run_task(self_):
                return PDFEncryptor().decrypt(self_.src, self_.out, self_.pwd)

        w = DecWorker(self._dec_path, out, pwd)
        w.signals.finished.connect(lambda p: (
            self._dec_progress.set_finished(True),
            finish_output_task(self, "解密完成", p),
        ))
        w.signals.error.connect(lambda msg: (
            self._dec_progress.set_finished(False, msg),
            show_error(self, "解密失败", msg),
        ))
        submit_worker(w)
