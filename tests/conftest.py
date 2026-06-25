"""
PDF Studio - pytest 共享 fixtures
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """生成一个简单的测试 PDF"""
    pdf_path = tmp_path / "test.pdf"
    try:
        import fitz

        doc = fitz.open()
        for i in range(5):
            page = doc.new_page(width=595, height=842)
            page.insert_text(
                fitz.Point(72, 72),
                f"Test Page {i + 1}\nPDF Studio Unit Test",
                fontsize=24,
            )
        doc.save(str(pdf_path))
        doc.close()
    except ImportError:
        pytest.skip("PyMuPDF (fitz) 未安装")
    return pdf_path


@pytest.fixture
def sample_image(tmp_path) -> Path:
    """生成一张测试图片"""
    img_path = tmp_path / "test.png"
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), "PDF Studio Test Image", fill=(0, 0, 0))
        draw.rectangle([100, 100, 700, 500], outline=(0, 0, 255), width=3)
        img.save(str(img_path))
    except ImportError:
        pytest.skip("Pillow 未安装")
    return img_path


@pytest.fixture(scope="session")
def qapp():
    """全 session 共享 QApplication，避免 qfluentwidgets QConfig 被提前销毁"""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    from qfluentwidgets import setTheme, Theme

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    setTheme(Theme.AUTO)
    return app


def _external_test_roots() -> list[Path]:
    env_root = os.getenv("PDF_STUDIO_TEST_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend(
        [
            Path(r"D:\pdf-studio测试文件"),
            Path(r"D:\测试文件"),
        ]
    )
    return [p for p in candidates if p.exists()]


@pytest.fixture(scope="session")
def integration_test_root(tmp_path_factory) -> Path:
    """
    集成测试数据根目录：
    1) PDF_STUDIO_TEST_ROOT 或本地样本目录（若存在）
    2) 否则在临时目录生成最小 pdf/ 与 图片/ 结构
    """
    for root in _external_test_roots():
        pdf_dir = root / "pdf"
        if pdf_dir.exists() and list(pdf_dir.glob("*.pdf")):
            return root

    root = tmp_path_factory.mktemp("pdf_studio_integration")
    pdf_dir = root / "pdf"
    img_dir = root / "图片"
    pdf_dir.mkdir()
    img_dir.mkdir()

    try:
        import fitz

        pdf_path = pdf_dir / "generated.pdf"
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=595, height=842)
            page.insert_text(
                fitz.Point(72, 72),
                f"Integration Page {i + 1}",
                fontsize=20,
            )
        doc.save(str(pdf_path))
        doc.close()
    except ImportError:
        pytest.skip("PyMuPDF (fitz) 未安装，无法生成集成测试 PDF")

    try:
        from PIL import Image, ImageDraw

        img_path = img_dir / "generated.png"
        img = Image.new("RGB", (400, 300), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "Integration Test", fill=(0, 0, 0))
        img.save(str(img_path))
    except ImportError:
        pass

    return root


@pytest.fixture(scope="session")
def integration_pdf_dir(integration_test_root) -> Path:
    return integration_test_root / "pdf"


@pytest.fixture(scope="session")
def integration_img_dir(integration_test_root) -> Path:
    return integration_test_root / "图片"
