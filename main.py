"""
PDF Studio - 应用主入口
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# ── 确保项目根目录在 sys.path ─────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 高DPI支持（需在QApplication之前设置）──────
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

# Windows：在 Qt 之前初始化 PyMuPDF，降低与 PyQt6 同进程加载时的冲突概率
import fitz  # noqa: F401

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from app.utils.logger import setup_logger, logger
from app.config.settings import settings_mgr
from app.config.constants import APP_NAME, APP_VERSION, CACHE_DIR, TEMP_DIR


def init_directories() -> None:
    """初始化必要目录（不创建 logs）"""
    for d in [CACHE_DIR, TEMP_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def create_app() -> QApplication:
    """创建并配置 QApplication"""
    # PyQt6 高DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("PDFStudio")

    # 默认字体（中文优先）
    font = QFont()
    font.setFamilies(["Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)

    return app


def main() -> int:
    """应用主函数"""
    if "--pack-smoke" in sys.argv:
        from pathlib import Path
        import traceback

        from app.utils.pack_smoke import run_pack_smoke, smoke_result_path

        try:
            return run_pack_smoke()
        except Exception:
            smoke_result_path().write_text(
                f"FAIL: {traceback.format_exc()}\n",
                encoding="utf-8",
            )
            return 1

    # 1. 初始化目录
    init_directories()

    # 2. 初始化运行时配置
    settings_mgr.apply_runtime_settings()
    logger.info(f"{'='*50}")
    logger.info(f"{APP_NAME} v{APP_VERSION} 启动")
    logger.info(f"Python: {sys.version.split()[0]}  Platform: {sys.platform}")
    logger.info(f"{'='*50}")

    from app.utils.deps import format_missing_dependencies_message, verify_core_dependencies

    missing_deps = verify_core_dependencies()
    if missing_deps:
        logger.warning(format_missing_dependencies_message(missing_deps))

    # 3. 创建 QApplication
    app = create_app()

    # 4. 创建并显示主窗口
    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    from app.ui.setup_wizard import show_setup_wizard_if_needed
    show_setup_wizard_if_needed(window)

    logger.info("主窗口已显示，进入事件循环")

    # 5. 运行事件循环
    exit_code = app.exec()

    logger.info(f"{APP_NAME} 退出，代码：{exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
