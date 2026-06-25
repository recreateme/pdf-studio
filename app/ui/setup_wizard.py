"""
PDF Studio - 首次启动 / 依赖检查向导
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
)
from qfluentwidgets import (
    TitleLabel, BodyLabel, CaptionLabel, SubtitleLabel,
    PrimaryPushButton, PushButton, CheckBox, TextEdit,
)

from app.config.constants import APP_NAME
from app.config.settings import settings_mgr
from app.utils.deps import (
    DependencyStatus,
    get_setup_dependency_report,
    format_setup_install_commands,
)


class SetupWizardDialog(QDialog):
    """首次启动向导：产品定位说明 + 依赖状态 + 安装命令"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - 欢迎使用")
        self.setMinimumSize(560, 520)
        self._report = get_setup_dependency_report()
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        root.addWidget(TitleLabel(f"欢迎使用 {APP_NAME}"))
        root.addWidget(BodyLabel(
            "WPS 免费版 PDF 工具箱补位 · 本地离线 · 无广告"
        ))
        root.addWidget(CaptionLabel(
            "在 WPS 中阅读与写文档；需要拆分、合并、压缩、加密、"
            "水印、OCR 等会员 PDF 功能时，请使用本工具处理。"
        ))

        root.addWidget(SubtitleLabel("依赖状态"))
        status_host = QVBoxLayout()
        status_host.setSpacing(6)
        for item in self._report:
            status_host.addWidget(self._build_status_row(item))
        root.addLayout(status_host)

        root.addWidget(SubtitleLabel("推荐安装命令（可复制）"))
        self._cmd_edit = TextEdit()
        self._cmd_edit.setReadOnly(True)
        self._cmd_edit.setFixedHeight(120)
        self._cmd_edit.setPlainText(format_setup_install_commands(self._report))
        root.addWidget(self._cmd_edit)

        copy_btn = PushButton("复制命令")
        copy_btn.clicked.connect(self._copy_commands)
        root.addWidget(copy_btn, alignment=Qt.AlignmentFlag.AlignRight)

        root.addWidget(CaptionLabel(
            "说明：PDF 核心处理无需联网；OCR 首次识别会下载模型；"
            "网页转 PDF 需 Playwright 或本机 Chrome/Edge。"
        ))

        self._skip_cb = CheckBox("下次启动不再显示此向导")
        self._skip_cb.setChecked(True)
        root.addWidget(self._skip_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = PrimaryPushButton("开始使用")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _build_status_row(item: DependencyStatus) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        mark = "✓" if item.available else "✗"
        color = "#107C10" if item.available else "#E74856"
        mark_label = BodyLabel(mark)
        mark_label.setFixedWidth(16)
        mark_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        tier = "必选" if item.required else "可选"
        name_label = BodyLabel(f"[{tier}] {item.name}")
        detail = item.version if item.available else (item.install_hint or "未安装")
        detail_label = CaptionLabel(detail[:80])
        detail_label.setStyleSheet("color: #888;")

        layout.addWidget(mark_label)
        layout.addWidget(name_label, 1)
        layout.addWidget(detail_label)
        return row

    def _copy_commands(self) -> None:
        text = self._cmd_edit.toPlainText()
        QGuiApplication.clipboard().setText(text)

    def mark_completed(self) -> None:
        if self._skip_cb.isChecked():
            settings_mgr.general.setup_wizard_completed = True
            settings_mgr.save()


def should_show_setup_wizard() -> bool:
    return not settings_mgr.general.setup_wizard_completed


def show_setup_wizard_if_needed(parent=None) -> None:
    if not should_show_setup_wizard():
        return
    dialog = SetupWizardDialog(parent)
    dialog.exec()
    dialog.mark_completed()
