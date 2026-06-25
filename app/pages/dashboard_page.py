"""
PDF Studio - 首页 Dashboard
显示快捷入口、最近文件、统计信息
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QLabel,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea, CardWidget, BodyLabel, TitleLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    FluentIcon, IconWidget, SubtitleLabel,
    StrongBodyLabel,
)

from app.config.constants import (
    APP_NAME, APP_VERSION, SUPPORTED_PDF_EXTENSIONS, DASHBOARD_WPS_BADGES,
)
from app.config.settings import settings_mgr
from app.widgets.task_queue_panel import TaskQueuePanel


class QuickActionCard(CardWidget):
    """快捷功能卡片"""

    def __init__(
        self,
        icon,
        title: str,
        desc: str,
        color: str,
        route_key: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(112)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        icon_container = QWidget()
        icon_container.setFixedSize(52, 52)
        icon_container.setStyleSheet(f"""
            background: {color}22;
            border-radius: 10px;
        """)
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_widget = IconWidget(icon)
        icon_widget.setFixedSize(28, 28)
        icon_widget.setStyleSheet(f"color: {color};")
        icon_layout.addWidget(icon_widget)

        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        title_label = StrongBodyLabel(title)
        desc_label = CaptionLabel(desc)
        desc_label.setStyleSheet("color: #888;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        badge_text = DASHBOARD_WPS_BADGES.get(route_key, "")
        if badge_text:
            badge = CaptionLabel(badge_text)
            badge.setStyleSheet(
                f"color: {color}; font-size: 11px; padding: 1px 0;"
            )
            text_layout.addWidget(badge)

        layout.addWidget(icon_container)
        layout.addWidget(text_widget, 1)
        layout.addWidget(IconWidget(FluentIcon.CHEVRON_RIGHT))


class RecentFileItem(QWidget):
    """最近文件列表条目"""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        p = Path(path)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        icon = IconWidget(FluentIcon.DOCUMENT)
        icon.setFixedSize(20, 20)

        name_label = BodyLabel(p.name)
        name_label.setToolTip(path)

        dir_label = CaptionLabel(str(p.parent)[:40] + ("..." if len(str(p.parent)) > 40 else ""))
        dir_label.setStyleSheet("color: #999;")

        open_btn = PushButton("系统打开")
        open_btn.setFixedWidth(72)
        open_btn.clicked.connect(self._open_file)

        layout.addWidget(icon)
        layout.addWidget(name_label, 1)
        layout.addWidget(dir_label)
        if p.suffix.lower() in SUPPORTED_PDF_EXTENSIONS:
            read_btn = PushButton("阅读器")
            read_btn.setFixedWidth(64)
            read_btn.clicked.connect(self._open_in_reader)
            layout.addWidget(read_btn)
        layout.addWidget(open_btn)

        self.setStyleSheet("""
            RecentFileItem:hover { background: rgba(128,128,128,0.06); border-radius: 6px; }
        """)

    def _open_file(self):
        from app.utils.helpers import open_file
        try:
            open_file(self.path)
        except Exception as e:
            from app.widgets.common import show_warning
            show_warning(self.window(), "打开失败", str(e))

    def _open_in_reader(self):
        win = self.window()
        if hasattr(win, "open_pdf_in_reader"):
            win.open_pdf_in_reader(self.path)


class DashboardPage(ScrollArea):
    """首页 - 快捷操作 + 最近文件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashboardPage")
        self._setup_ui()

    def _setup_ui(self):
        # 主容器
        container = QWidget()
        self.setWidget(container)
        self.setWidgetResizable(True)

        root = QVBoxLayout(container)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(28)

        # ── 欢迎标题 ──────────────────────────
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        title = TitleLabel(f"欢迎使用 {APP_NAME}")
        subtitle = BodyLabel("WPS 免费版 PDF 工具箱补位 · 本地离线 · 无广告")
        subtitle.setStyleSheet("color: #888;")
        version_label = CaptionLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color: #aaa;")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addWidget(version_label)
        root.addWidget(header)

        # ── 快捷操作 ──────────────────────────
        root.addWidget(SubtitleLabel("快捷操作"))

        actions_grid = QGridLayout()
        actions_grid.setSpacing(12)

        actions = [
            (FluentIcon.CUT,       "PDF 拆分",  "按页面、书签、大小拆分",   "#0078D4", "split"),
            (FluentIcon.ADD,       "PDF 合并",  "多文件合并，支持书签目录",   "#107C10", "merge"),
            (FluentIcon.VIEW,      "PDF 对比",  "页数/体积/文本轻量对比",     "#0078D4", "compare"),
            (FluentIcon.COPY,      "页面管理",  "提取/删除/旋转 PDF 页面",    "#5C2D91", "pages"),
            (FluentIcon.DOCUMENT,  "阅读批注",  "连续阅读 · 搜索 · 批注",     "#0078D4", "reader"),
            (FluentIcon.ZIP_FOLDER,"PDF 压缩",  "含智能压缩，保留文字层",     "#FF8C00", "compress"),
            (FluentIcon.SEARCH,    "OCR 识别",  "中英日文离线识别，多格式导出", "#C239B3", "ocr"),
            (FluentIcon.PHOTO,     "图片工具",  "PDF↔图片互转，图像增强",   "#00B7C3", "image"),
            (FluentIcon.GLOBE,     "网页转PDF", "内置Chromium，支持懒加载", "#E74856", "web"),
            (FluentIcon.DEVELOPER_TOOLS,"PDF 工具","去水印 · 表单 · 签名",   "#8764B8", "tools"),
            (FluentIcon.FINGERPRINT,"加密解密", "密码保护与权限控制",        "#7A7574", "encrypt"),
            (FluentIcon.CALORIES,  "批处理中心","工作流自动化批量处理",      "#69797E", "batch"),
        ]

        main_window = self.window()
        for i, (icon, title, desc, color, page) in enumerate(actions):
            card = QuickActionCard(icon, title, desc, color, route_key=page)
            card.clicked.connect(lambda checked=False, p=page: self._navigate(p))
            actions_grid.addWidget(card, i // 2, i % 2)

        root.addLayout(actions_grid)

        root.addWidget(SubtitleLabel("后台任务"))
        self._task_panel = TaskQueuePanel()
        root.addWidget(self._task_panel)

        # ── 最近文件 ──────────────────────────
        root.addWidget(SubtitleLabel("最近打开"))

        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(2)
        root.addWidget(self._recent_container)

        self._refresh_recent()
        root.addStretch()

    def _navigate(self, page_name: str):
        win = self.window()
        if hasattr(win, "navigate_to"):
            win.navigate_to(page_name)

    def _refresh_recent(self):
        # 清空
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        recent = settings_mgr.settings.recent_files
        if not recent:
            empty = CaptionLabel("暂无最近文件")
            empty.setStyleSheet("color: #aaa; padding: 12px;")
            self._recent_layout.addWidget(empty)
        else:
            for path in recent[:10]:
                if Path(path).exists():
                    item = RecentFileItem(path)
                    self._recent_layout.addWidget(item)

        clear_btn = PushButton("清除记录")
        clear_btn.setFixedWidth(100)
        clear_btn.clicked.connect(self._clear_recent)
        self._recent_layout.addWidget(clear_btn)

    def _clear_recent(self):
        settings_mgr.clear_recent_files()
        self._refresh_recent()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_recent()
        if hasattr(self, "_task_panel"):
            self._task_panel.refresh()
