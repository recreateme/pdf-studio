"""
PDF Studio - 集成测试
优先级：
1) 环境变量 PDF_STUDIO_TEST_ROOT
2) D:\\pdf-studio测试文件 / D:\\测试文件
3) conftest 自动生成的临时样本
运行：python -m pytest tests/test_integration.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _skip_if_no_pdfs(pdf_dir: Path) -> list[Path]:
    if not pdf_dir.exists():
        pytest.skip(f"测试目录不存在: {pdf_dir}")
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        pytest.skip(f"未找到 PDF 测试文件: {pdf_dir}")
    return pdfs


def _first_pdf(pdf_dir: Path) -> Path:
    return _skip_if_no_pdfs(pdf_dir)[0]


def _all_pdfs(pdf_dir: Path) -> list[Path]:
    return _skip_if_no_pdfs(pdf_dir)


def _test_images(img_dir: Path) -> list[Path]:
    if not img_dir.exists():
        pytest.skip(f"测试目录不存在: {img_dir}")
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif"}
    imgs = [p for p in img_dir.iterdir() if p.suffix.lower() in exts]
    if not imgs:
        pytest.skip(f"未找到图片测试文件: {img_dir}")
    return sorted(imgs)[:5]


# ─────────────────────────────────────────────
# PDF 读取
# ─────────────────────────────────────────────

class TestIntegrationPDFReader:
    def test_get_info_all_pdfs(self, integration_pdf_dir):
        from core.pdf.processor import PDFReader
        for pdf in _all_pdfs(integration_pdf_dir):
            info = PDFReader.get_info(pdf)
            assert info.page_count > 0, f"{pdf.name} 页数为0"
            assert info.file_size > 0

    def test_render_thumbnail(self, integration_pdf_dir):
        from core.pdf.processor import PDFReader
        pdf = _first_pdf(integration_pdf_dir)
        data = PDFReader.render_thumbnail(pdf, 0, width=120)
        assert data[:4] == b"\x89PNG"


# ─────────────────────────────────────────────
# PDF 拆分 / 合并 / 压缩
# ─────────────────────────────────────────────

class TestIntegrationPDFSplitMerge:
    def test_split_by_count(self, integration_pdf_dir, tmp_path):
        from core.pdf.processor import PDFSplitter, SplitOptions, PDFReader
        pdf = _first_pdf(integration_pdf_dir)
        info = PDFReader.get_info(pdf)
        if info.page_count < 2:
            pytest.skip("页数不足")
        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        outputs = PDFSplitter().split_by_count(pdf, 1, options)
        assert len(outputs) == info.page_count
        assert all(p.exists() and p.stat().st_size > 0 for p in outputs)

    def test_merge_two_pdfs(self, integration_pdf_dir, tmp_path):
        from core.pdf.processor import PDFMerger, MergeOptions, PDFReader
        pdfs = _all_pdfs(integration_pdf_dir)[:2]
        if len(pdfs) < 2:
            pytest.skip("PDF 不足2个")
        out = tmp_path / "merged.pdf"
        PDFMerger().merge(pdfs, MergeOptions(output_path=out, overwrite=True))
        assert out.exists()
        info = PDFReader.get_info(out)
        total = sum(PDFReader.get_info(p).page_count for p in pdfs)
        assert info.page_count == total

    def test_compress(self, integration_pdf_dir, tmp_path):
        from core.pdf.processor import PDFCompressor, CompressOptions
        pdf = _first_pdf(integration_pdf_dir)
        out = tmp_path / "compressed.pdf"
        result = PDFCompressor().compress(
            pdf, CompressOptions(output_path=out, mode="balanced", overwrite=True)
        )
        assert result.path.exists() and result.compressed_size > 0


# ─────────────────────────────────────────────
# 加密 / 水印 / 页码
# ─────────────────────────────────────────────

class TestIntegrationPDFSecurity:
    def test_encrypt_decrypt_roundtrip(self, integration_pdf_dir, tmp_path):
        pytest.importorskip("cryptography")
        from core.pdf.processor import PDFEncryptor, PDFReader
        pdf = _first_pdf(integration_pdf_dir)
        enc = tmp_path / "encrypted.pdf"
        dec = tmp_path / "decrypted.pdf"
        PDFEncryptor().encrypt(pdf, enc, user_password="test123")
        assert enc.exists()
        info = PDFReader.get_info(enc, password="test123")
        assert info.has_password
        PDFEncryptor().decrypt(enc, dec, password="test123")
        assert dec.exists()
        info2 = PDFReader.get_info(dec)
        assert not info2.has_password

    def test_watermark_and_page_numbers(self, integration_pdf_dir, tmp_path):
        from core.pdf.processor import (
            PDFWatermarker, PDFPageNumberer,
            WatermarkOptions, PageNumberOptions,
        )
        pdf = _first_pdf(integration_pdf_dir)
        wm_out = tmp_path / "watermarked.pdf"
        PDFWatermarker().add_text_watermark(
            pdf, wm_out,
            WatermarkOptions(text="PDF Studio Test", opacity=0.3, rotation=45),
        )
        assert wm_out.exists()
        pn_out = tmp_path / "numbered.pdf"
        PDFPageNumberer().add_page_numbers(
            wm_out, pn_out,
            PageNumberOptions(format_str="{n}/{total}", position="bottom_center"),
        )
        assert pn_out.exists()


# ─────────────────────────────────────────────
# 图片转换
# ─────────────────────────────────────────────

class TestIntegrationImage:
    def test_pdf_to_image(self, integration_pdf_dir, tmp_path):
        from core.image.converter import PDFToImageConverter, PDFToImageOptions
        pdf = _first_pdf(integration_pdf_dir)
        options = PDFToImageOptions(
            output_dir=tmp_path, format="PNG", dpi=72, pages=[0]
        )
        outputs = PDFToImageConverter().convert(pdf, options)
        assert len(outputs) == 1
        assert outputs[0].suffix.lower() == ".png"

    def test_images_to_pdf(self, integration_img_dir, tmp_path):
        from core.image.converter import ImageToPDFConverter, ImageToPDFOptions
        imgs = _test_images(integration_img_dir)[:3]
        out = tmp_path / "from_images.pdf"
        result = ImageToPDFConverter().convert(
            imgs, ImageToPDFOptions(output_path=out, page_size="A4")
        )
        assert result.exists()
        import fitz
        doc = fitz.open(str(result))
        assert len(doc) >= 1
        doc.close()


# ─────────────────────────────────────────────
# OCR（可选，模型首次加载较慢）
# ─────────────────────────────────────────────

class TestIntegrationOCR:
    def test_ocr_single_page(self, integration_pdf_dir, tmp_path):
        from core.ocr.engine import OCRManager, OCROptions
        manager = OCRManager()
        if not manager.is_available:
            pytest.skip("OCR 引擎不可用")
        pdf = _first_pdf(integration_pdf_dir)
        options = OCROptions(dpi=72, pages=[0], confidence_threshold=0.3)
        results = manager.ocr_pdf(pdf, options)
        assert len(results) >= 1

    def test_ocr_image(self, integration_img_dir):
        from core.ocr.engine import OCRManager, OCROptions
        manager = OCRManager()
        if not manager.is_available:
            pytest.skip("OCR 引擎不可用")
        img = _test_images(integration_img_dir)[0]
        result = manager.ocr_image(img, OCROptions(confidence_threshold=0.3))
        assert result.page_index == 0


# ─────────────────────────────────────────────
# 批注 / 对比
# ─────────────────────────────────────────────

class TestIntegrationExtras:
    def test_compare_pdfs(self, integration_pdf_dir, tmp_path):
        from core.pdf.compare import PDFCompareService
        pdf_a = _first_pdf(integration_pdf_dir)
        pdf_b = tmp_path / "copy.pdf"
        import shutil
        shutil.copy2(pdf_a, pdf_b)
        result = PDFCompareService().compare(pdf_a, pdf_b)
        assert result.page_count_a >= 1
        assert result.page_count_match is True


# ─────────────────────────────────────────────
# 网页转 PDF（需 Playwright / 系统浏览器）
# ─────────────────────────────────────────────

class TestIntegrationWeb:
    def test_url_to_pdf(self, tmp_path):
        from core.web.processor import WebProcessor, WebToPDFOptions

        proc = WebProcessor()
        if not proc.is_playwright_available():
            pytest.skip("Playwright 不可用")
        out = tmp_path / "web.pdf"
        options = WebToPDFOptions(
            output_path=out,
            wait_timeout=30,
            wait_after_load=1.0,
            scroll_to_bottom=False,
        )
        result = proc.url_to_pdf("https://example.com", options)
        assert result.exists() and result.stat().st_size > 1000
