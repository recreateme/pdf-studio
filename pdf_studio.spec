# -*- mode: python ; coding: utf-8 -*-
"""
pd-studio - PyInstaller 打包配置

用法：
  pyinstaller pdf_studio.spec
  # 或：python scripts/pack_smoke.py

输出：
  dist/PDFStudio/PDFStudio.exe

说明：
  - 目录模式（onedir），便于携带 cryptography / Qt 等依赖
  - 图标：app/resources/icons/app.ico
  - 窗口标题由应用内常量控制：pd-studio 1299800632@qq.com
  - Playwright / PaddleOCR 不随包分发；网页转 PDF 可回退系统 Chrome/Edge
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# PyInstaller 注入 SPECPATH；以 spec 所在目录为项目根
ROOT = Path(SPECPATH).resolve()  # noqa: F821

block_cipher = None

# ── 应用图标与版本资源 ─────────────────────────
APP_ICON = ROOT / "app" / "resources" / "icons" / "app.ico"
EXE_ICON = str(APP_ICON) if APP_ICON.is_file() else None
VERSION_FILE = ROOT / "app" / "resources" / "version_info.txt"
EXE_VERSION = (
    str(VERSION_FILE)
    if sys.platform == "win32" and VERSION_FILE.is_file()
    else None
)

# cryptography 全量收集（含 hazmat 与本地扩展），避免打包后 AES 加密失效
_crypto_datas, _crypto_binaries, _crypto_hiddenimports = collect_all("cryptography")

# Conda 运行时 DLL（pyexpat/_ctypes/_bz2/_lzma 依赖）
_CONDA_DLL_NAMES = (
    "libexpat.dll",
    "expat.dll",
    "ffi.dll",
    "libbz2.dll",
    "liblzma.dll",
    "zlib.dll",
)
_conda_bin = Path(sys.prefix) / "Library" / "bin"
_runtime_binaries = [
    (str(_conda_bin / name), ".")
    for name in _CONDA_DLL_NAMES
    if (_conda_bin / name).is_file()
]

# ── 隐藏导入 ──────────────────────────────────
hidden_imports = [
    # PyQt6
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    "PyQt6.sip",
    # Fluent Widgets
    "qfluentwidgets",
    "qfluentwidgets.common",
    "qfluentwidgets.components",
    "qfluentwidgets.window",
    # PDF
    "fitz",
    "pymupdf",
    "pypdf",
    "pypdfium2",
    "pypdf._crypt_providers",
    "pypdf._crypt_providers._base",
    "pypdf._crypt_providers._cryptography",
    # 图像
    "PIL",
    "PIL.Image",
    "PIL.ImageFilter",
    "PIL.ImageEnhance",
    "PIL.ImageDraw",
    "cv2",
    "numpy",
    # OCR（可选，按需加载）
    "rapidocr_onnxruntime",
    "onnxruntime",
    # 配置 / logger / 文档
    "loguru",
    "pydantic",
    "pydantic_core",
    "yaml",
    "docx",
    "cryptography",
    "cryptography.hazmat.primitives.ciphers.algorithms",
    "cryptography.hazmat.primitives.ciphers.modes",
    "cryptography.hazmat.primitives.ciphers.base",
    "cryptography.hazmat.primitives.padding",
    "xml.parsers.expat",
    # 应用包
    "app",
    "app.config",
    "app.config.constants",
    "app.config.settings",
    "app.ui",
    "app.ui.main_window",
    "app.ui.setup_wizard",
    "app.ui.app_styles",
    "app.pages",
    "app.pages.dashboard_page",
    "app.pages.split_page",
    "app.pages.merge_page",
    "app.pages.compare_page",
    "app.pages.pages_manage_page",
    "app.pages.reader_page",
    "app.pages.compress_page",
    "app.pages.encrypt_page",
    "app.pages.watermark_page",
    "app.pages.tools_page",
    "app.pages.image_page",
    "app.pages.ocr_page",
    "app.pages.web_page",
    "app.pages.settings_page",
    "app.widgets",
    "app.widgets.common",
    "app.widgets.combo_box",
    "app.widgets.image_merge_list",
    "app.widgets.list_styles",
    "app.widgets.pdf_page_view",
    "app.widgets.task_queue_panel",
    "app.workers",
    "app.workers.base_worker",
    "app.utils",
    "app.utils.deps",
    "app.utils.helpers",
    "app.utils.logger",
    "app.utils.task_hub",
    "app.utils.render_cache",
    "app.utils.pack_smoke",
    "core",
    "core.pdf",
    "core.pdf.processor",
    "core.pdf.annotations",
    "core.pdf.viewer",
    "core.pdf.compare",
    "core.pdf.extras",
    "core.image",
    "core.image.converter",
    "core.image.merger",
    "core.image.compressor",
    "core.ocr",
    "core.ocr.engine",
    "core.web",
    "core.web.processor",
]
hidden_imports += _crypto_hiddenimports

# ── 数据文件 ──────────────────────────────────
_icon_dir = APP_ICON.parent
_icon_dir.mkdir(parents=True, exist_ok=True)
datas = [(str(_icon_dir), "app/resources/icons")]
datas += _crypto_datas
datas += collect_data_files("qfluentwidgets", include_py_files=False)

# ── 分析 ──────────────────────────────────────
a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=_crypto_binaries + _runtime_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "pytest_qt",
        "playwright",
        "paddleocr",
        "paddle",
        "torch",
        "tensorflow",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed：无控制台黑窗
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=EXE_ICON,
    version=EXE_VERSION,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFStudio",
)
