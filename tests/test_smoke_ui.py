"""
PDF Studio - 最小 UI Smoke 测试（需 PyQt6；pytest-qt 可选）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")

HAS_PYTEST_QT = __import__("importlib").util.find_spec("pytestqt") is not None


@pytest.mark.skipif(not HAS_PYTEST_QT, reason="未安装 pytest-qt，跳过 widget 交互测试")
class TestSmokeUIPages:
    def test_settings_page_instantiates(self, qapp, qtbot):
        from app.pages.settings_page import SettingsPage

        page = SettingsPage()
        qtbot.addWidget(page)
        assert page.objectName() == "settingsPage"

    def test_compare_page_instantiates(self, qapp, qtbot):
        from app.pages.compare_page import ComparePage

        page = ComparePage()
        qtbot.addWidget(page)
        assert page.objectName() == "comparePage"

    def test_dashboard_page_instantiates(self, qapp, qtbot):
        from app.pages.dashboard_page import DashboardPage

        page = DashboardPage()
        qtbot.addWidget(page)
        assert page.objectName() == "dashboardPage"


def test_settings_page_without_qtbot(qapp):
    """无 pytest-qt 时仍可验证页面可构造"""
    from app.pages.settings_page import SettingsPage

    page = SettingsPage()
    assert page.objectName() == "settingsPage"


def test_app_icon_assets_exist():
    from app.config.constants import ICONS_DIR

    ico = ICONS_DIR / "app.ico"
    png = ICONS_DIR / "app.png"
    assert ico.is_file(), "缺少 app.ico，请运行 python scripts/generate_app_icon.py"
    assert png.is_file(), "缺少 app.png"
    assert ico.stat().st_size > 100
