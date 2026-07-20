"""
PDF Studio - 主窗口
基于 PyQt6-Fluent-Widgets 的现代 Fluent Design 界面
左侧导航栏 + 内容区域布局
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QCloseEvent
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import (
    NavigationItemPosition,
    FluentWindow,
    FluentIcon,
    SplashScreen,
    setTheme, Theme, setThemeColor,
)
from qfluentwidgets.components.navigation import NavigationDisplayMode

from app.config.constants import (
    APP_NAME, APP_VERSION, APP_WINDOW_TITLE,
    MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT,
    MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT,
    THEME_COLOR_LIGHT, ICONS_DIR,
)
from app.config.settings import settings_mgr
from app.utils.logger import logger

# 页面导入（延迟导入避免循环）
from app.pages.dashboard_page import DashboardPage
from app.pages.split_page import SplitPage
from app.pages.merge_page import MergePage
from app.pages.web_page import WebPage
from app.pages.ocr_page import OCRPage
from app.pages.image_page import ImagePage
from app.pages.compress_page import CompressPage
from app.pages.encrypt_page import EncryptPage
from app.pages.watermark_page import WatermarkPage
from app.pages.pages_manage_page import PagesManagePage
from app.pages.reader_page import ReaderPage
from app.pages.tools_page import ToolsPage
from app.pages.compare_page import ComparePage
from app.pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    """
    PDF Studio 主窗口

    布局：FluentWindow 提供左侧折叠导航 + 右侧内容区域
    """

    def __init__(self) -> None:
        super().__init__()
        self._init_window()
        self._init_pages()
        self._init_nav()
        self._apply_navigation_labels(settings_mgr.general.show_toolbar_labels)
        self._restore_geometry()
        self._init_task_hub()
        logger.info(f"{APP_NAME} v{APP_VERSION} 主窗口初始化完成")

    # ── 窗口初始化 ────────────────────────────

    def _init_window(self) -> None:
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self.resize(MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT)

        # 主题
        s = settings_mgr.general
        if s.theme == "dark":
            setTheme(Theme.DARK)
        elif s.theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

        setThemeColor(THEME_COLOR_LIGHT)

        from app.ui.app_styles import apply_app_styles
        apply_app_styles()

        icon_path = self._resolve_app_icon_path()
        if icon_path is not None:
            icon = QIcon(str(icon_path))
            self.setWindowIcon(icon)
            # Fluent 标题栏左上角图标
            if hasattr(self, "setIcon"):
                self.setIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

    def _apply_navigation_labels(self, show_labels: bool) -> None:
        """根据设置展开/收起导航栏文字标签"""
        nav = self.navigationInterface
        if show_labels:
            nav.setMinimumExpandWidth(900)
            nav.expand(useAni=False)
            return
        nav.setMinimumExpandWidth(100000)
        if nav.panel.displayMode == NavigationDisplayMode.EXPAND:
            nav.toggle()

    def apply_general_settings(self) -> None:
        """应用通用设置（由设置页保存后调用）"""
        s = settings_mgr.general
        if s.theme == "dark":
            setTheme(Theme.DARK)
        elif s.theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)
        from app.ui.app_styles import apply_app_styles
        apply_app_styles()
        self._apply_navigation_labels(s.show_toolbar_labels)
        self._refresh_theme_dependent_widgets()

    def _refresh_theme_dependent_widgets(self) -> None:
        """主题切换后刷新列表、阅读器等依赖主题的控件样式。"""
        from PyQt6.QtWidgets import QListWidget

        from app.widgets.list_styles import apply_list_widget_style

        for lst in self.findChildren(QListWidget):
            apply_list_widget_style(lst)
        if hasattr(self, "reader_page"):
            self.reader_page._apply_reader_theme()

    def _init_task_hub(self) -> None:
        """连接全局任务队列通知"""
        from app.utils.task_hub import TaskHub
        from app.widgets.common import show_info, show_warning

        hub = TaskHub.instance()
        hub.taskQueued.connect(
            lambda name, pos: show_info(
                self,
                "任务已排队",
                f"「{name}」已加入队列（前面 {pos} 个任务等待中）",
            )
        )
        hub.queueRejected.connect(
            lambda name, limit: show_warning(
                self,
                "任务队列已满",
                f"「{name}」无法提交。请等待任务完成，或在设置中提高队列上限（当前 {limit}）。",
            )
        )

    @staticmethod
    def _resolve_app_icon_path() -> Path | None:
        """开发/打包环境下解析应用图标路径"""
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "app" / "resources" / "icons" / "app.ico")
            candidates.append(Path(sys.executable).parent / "app" / "resources" / "icons" / "app.ico")
        candidates.append(ICONS_DIR / "app.ico")
        for path in candidates:
            if path.is_file():
                return path
        return None

    # ── 页面实例化 ────────────────────────────

    def _init_pages(self) -> None:
        self.dashboard_page = DashboardPage(self)
        self.split_page     = SplitPage(self)
        self.merge_page     = MergePage(self)
        self.compare_page   = ComparePage(self)
        self.pages_manage_page = PagesManagePage(self)
        self.reader_page      = ReaderPage(self)
        self.tools_page       = ToolsPage(self)
        self.web_page       = WebPage(self)
        self.ocr_page       = OCRPage(self)
        self.image_page     = ImagePage(self)
        self.compress_page  = CompressPage(self)
        self.encrypt_page   = EncryptPage(self)
        self.watermark_page = WatermarkPage(self)
        self.settings_page  = SettingsPage(self)

    # ── 导航栏配置 ────────────────────────────

    def _init_nav(self) -> None:
        nav = self.navigationInterface

        # ── 主功能组 ─────────────────────────
        self.addSubInterface(
            self.dashboard_page,
            FluentIcon.HOME,
            "首页",
            NavigationItemPosition.TOP,
        )

        nav.addSeparator()

        self.addSubInterface(
            self.split_page,
            FluentIcon.CUT,
            "PDF 拆分",
        )
        self.addSubInterface(
            self.merge_page,
            FluentIcon.ADD,
            "PDF 合并",
        )
        self.addSubInterface(
            self.compare_page,
            FluentIcon.VIEW,
            "PDF 对比",
        )
        self.addSubInterface(
            self.pages_manage_page,
            FluentIcon.COPY,
            "页面管理",
        )
        self.addSubInterface(
            self.reader_page,
            FluentIcon.DOCUMENT,
            "阅读批注",
        )
        self.addSubInterface(
            self.compress_page,
            FluentIcon.ZIP_FOLDER,
            "PDF 压缩",
        )
        self.addSubInterface(
            self.encrypt_page,
            FluentIcon.FINGERPRINT,
            "加密解密",
        )
        self.addSubInterface(
            self.watermark_page,
            FluentIcon.EDIT,
            "水印页码",
        )
        self.addSubInterface(
            self.tools_page,
            FluentIcon.DEVELOPER_TOOLS,
            "PDF 工具",
        )

        nav.addSeparator()

        self.addSubInterface(
            self.image_page,
            FluentIcon.PHOTO,
            "图片工具",
        )
        self.addSubInterface(
            self.ocr_page,
            FluentIcon.SEARCH,
            "OCR 识别",
        )
        self.addSubInterface(
            self.web_page,
            FluentIcon.GLOBE,
            "网页转PDF",
        )

        # ── 底部组 ────────────────────────────
        self.addSubInterface(
            self.settings_page,
            FluentIcon.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
        )

    # ── 几何恢复 ──────────────────────────────

    def _restore_geometry(self) -> None:
        s = settings_mgr.general
        self.resize(s.window_width, s.window_height)
        if s.window_maximized:
            self.showMaximized()

    def closeEvent(self, event: QCloseEvent) -> None:
        """保存窗口状态"""
        s = settings_mgr.general
        s.window_maximized = self.isMaximized()
        if not self.isMaximized():
            s.window_width = self.width()
            s.window_height = self.height()
        settings_mgr.save()
        logger.info("主窗口关闭，配置已保存")
        super().closeEvent(event)

    # ── 公共接口 ──────────────────────────────

    def navigate_to(self, page_name: str) -> None:
        """跳转到指定页面"""
        page_map = {
            "split":    self.split_page,
            "merge":    self.merge_page,
            "compare":  self.compare_page,
            "pages":    self.pages_manage_page,
            "reader":   self.reader_page,
            "web":      self.web_page,
            "ocr":      self.ocr_page,
            "image":    self.image_page,
            "compress": self.compress_page,
            "encrypt":  self.encrypt_page,
            "watermark":self.watermark_page,
            "tools":    self.tools_page,
            "settings": self.settings_page,
        }
        if page_name in page_map:
            self.switchTo(page_map[page_name])

    def open_pdf_in_reader(self, path: str) -> None:
        """在应用内阅读器中打开 PDF"""
        self.navigate_to("reader")
        self.reader_page.open_document(path)
