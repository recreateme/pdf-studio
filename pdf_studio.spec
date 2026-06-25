# -*- mode: python ; coding: utf-8 -*-
"""
PDF Studio - PyInstaller 打包配置
用法：pyinstaller pdf_studio.spec
输出：dist/PDFStudio/PDFStudio.exe
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# PyInstaller 注入 SPECPATH；以 spec 所在目录为项目根
ROOT = Path(SPECPATH).resolve()

# cryptography 全量收集（含 hazmat 与本地扩展），避免打包后 AES 加密失效
_crypto_datas, _crypto_binaries, _crypto_hiddenimports = collect_all("cryptography")

# Conda 运行时 DLL（pyexpat/_ctypes/_bz2/_lzma 依赖，避免打包后 ImportError）
_CONDA_DLL_NAMES = (
    "libexpat.dll",
    "expat.dll",
    "ffi.dll",
    "libbz2.dll",
    "liblzma.dll",
    "zlib.dll",
)
_conda_prefix = Path(sys.prefix)
_conda_bin = _conda_prefix / "Library" / "bin"
_runtime_binaries = [
    (str(_conda_bin / name), ".")
    for name in _CONDA_DLL_NAMES
    if (_conda_bin / name).is_file()
]
# ── 应用图标（项目内资源，打包前请将 app.ico 置于该目录）──
APP_ICON = ROOT / "app" / "resources" / "icons" / "app.ico"
EXE_ICON = str(APP_ICON) if APP_ICON.is_file() else None
VERSION_FILE = ROOT / "app" / "resources" / "version_info.txt"
EXE_VERSION = str(VERSION_FILE) if sys.platform == "win32" and VERSION_FILE.is_file() else None

block_cipher = None

# ── 隐藏导入 ──────────────────────────────────
hidden_imports = [
    # PyQt6
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.sip",
    # Fluent Widgets
    "qfluentwidgets",
    "qfluentwidgets.common",
    "qfluentwidgets.components",
    # PDF
    "fitz",
    "pypdf",
    "pypdfium2",
    # 图像
    "PIL",
    "PIL.Image",
    "PIL.ImageFilter",
    "PIL.ImageEnhance",
    "cv2",
    "numpy",
    # OCR（可选模块，按需加载）
    "rapidocr_onnxruntime",
    "onnxruntime",
    # 其他
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
    "pypdf",
    "pypdf._crypt_providers",
    "pypdf._crypt_providers._base",
    "pypdf._crypt_providers._cryptography",
    "xml.parsers.expat",
    "app",
    "core",
    "app.config",
    "app.ui",
    "app.pages",
    "app.widgets",
    "app.workers",
    "app.utils",
    "app.utils.deps",
    "core.pdf",
    "core.image",
    "core.ocr",
    "core.web",
]
hidden_imports += _crypto_hiddenimports

# ── 数据文件 ──────────────────────────────────
_icon_dir = APP_ICON.parent
_icon_dir.mkdir(parents=True, exist_ok=True)
datas = [(str(_icon_dir), "app/resources/icons")]
datas += _crypto_datas
# Fluent Widgets 主题/样式资源
datas += collect_data_files("qfluentwidgets", include_py_files=False)

# Playwright 不随包分发（体积大且需单独 install chromium）；网页转 PDF 在打包版中仍可通过系统 Chrome/Edge 使用

# ── 分析 ──────────────────────────────────────
a = Analysis(
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
        "pytest",
        "playwright",
        "paddleocr",
        "paddle",
        "torch",
        "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=EXE_ICON,
    version=EXE_VERSION,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFStudio",
)
