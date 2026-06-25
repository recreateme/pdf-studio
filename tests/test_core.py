"""
PDF Studio - 核心功能单元测试
运行：pytest tests/ -v
"""
import io
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────
# 工具函数测试
# ─────────────────────────────────────────────

class TestHelpers:
    def test_get_file_size_str(self, tmp_path):
        from app.utils.helpers import get_file_size_str
        f = tmp_path / "test.txt"
        f.write_bytes(b"x" * 1024)
        assert "KB" in get_file_size_str(f)

    def test_get_unique_path(self, tmp_path):
        from app.utils.helpers import get_unique_path
        f = tmp_path / "output.pdf"
        f.write_text("x")
        unique = get_unique_path(f)
        assert unique != f
        assert "output_1" in unique.name

    def test_safe_filename(self):
        from app.utils.helpers import safe_filename
        assert "/" not in safe_filename("hello/world")
        assert "?" not in safe_filename("test?file")
        assert safe_filename("normal_name") == "normal_name"

    def test_collect_files(self, tmp_path):
        from app.utils.helpers import collect_files
        (tmp_path / "a.pdf").touch()
        (tmp_path / "b.pdf").touch()
        (tmp_path / "c.txt").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.pdf").touch()

        pdfs = collect_files(tmp_path, {".pdf"}, recursive=True)
        assert len(pdfs) == 3

        pdfs_flat = collect_files(tmp_path, {".pdf"}, recursive=False)
        assert len(pdfs_flat) == 2

    def test_is_pdf_valid(self, tmp_path, sample_pdf):
        from app.utils.helpers import is_pdf_valid
        assert is_pdf_valid(sample_pdf) is True
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        assert is_pdf_valid(bad) is False

    def test_chunked(self):
        from app.utils.helpers import chunked
        result = list(chunked([1, 2, 3, 4, 5], 2))
        assert result == [[1, 2], [3, 4], [5]]


# ─────────────────────────────────────────────
# 配置系统测试
# ─────────────────────────────────────────────

class TestSettings:
    def test_default_settings(self):
        from app.config.settings import AppSettings
        s = AppSettings()
        assert s.general.theme in ("auto", "light", "dark")
        assert s.pdf.default_dpi > 0
        assert isinstance(s.recent_files, list)

    def test_settings_serialization(self):
        from app.config.settings import AppSettings
        s = AppSettings()
        s.pdf.default_dpi = 180
        s.ocr.default_dpi = 220
        json_str = s.model_dump_json()
        s2 = AppSettings.model_validate_json(json_str)
        assert s.general.theme == s2.general.theme
        assert s2.pdf.default_dpi == 180
        assert s2.ocr.default_dpi == 220

    def test_resolve_output_dir(self, tmp_path):
        from app.config.settings import AppSettings, SettingsManager

        s = AppSettings()
        sample = tmp_path / "sample.pdf"
        sample.write_bytes(b"%PDF-1.4")

        mgr = SettingsManager.__new__(SettingsManager)
        mgr._settings = s

        s.pdf.default_output_dir = ""
        assert mgr.resolve_output_dir(sample) == sample.parent

        out = tmp_path / "outputs"
        s.pdf.default_output_dir = str(out)
        assert mgr.resolve_output_dir(sample) == out
        assert mgr.task_output_dir(sample, "_ocr") == out / "sample_ocr"

    def test_get_default_dpi_helpers(self):
        from app.config.constants import get_default_dpi, get_thumbnail_width, get_thumbnail_height

        assert get_default_dpi() >= 72
        assert get_thumbnail_width() >= 80
        assert get_thumbnail_height() >= 110


# ─────────────────────────────────────────────
# PDF 读取测试
# ─────────────────────────────────────────────

class TestPDFReader:
    def test_get_info(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFReader
        info = PDFReader.get_info(sample_pdf)
        assert info.page_count == 5
        assert info.file_size > 0
        assert not info.has_password

    def test_file_not_found(self):
        from core.pdf.processor import PDFReader
        with pytest.raises(FileNotFoundError):
            PDFReader.get_info("/nonexistent/file.pdf")

    def test_render_thumbnail(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFReader
        data = PDFReader.render_thumbnail(sample_pdf, 0, width=160)
        assert isinstance(data, bytes)
        assert data[:4] == b"\x89PNG"   # PNG 文件头

    def test_render_page(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFReader
        data = PDFReader.render_page(sample_pdf, 0, dpi=72)
        assert len(data) > 0


# ─────────────────────────────────────────────
# PDF 拆分测试
# ─────────────────────────────────────────────

class TestPDFSplitter:
    def test_split_by_ranges(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFSplitter, SplitOptions
        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        outputs = PDFSplitter().split_by_ranges(
            sample_pdf, [(0, 1), (2, 4)], options
        )
        assert len(outputs) == 2
        assert all(p.exists() for p in outputs)

    def test_split_by_count(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFSplitter, SplitOptions
        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        outputs = PDFSplitter().split_by_count(sample_pdf, 2, options)
        # 5页 / 2 = 3个文件
        assert len(outputs) == 3

    def test_extract_pages(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFSplitter
        out = tmp_path / "extracted.pdf"
        result = PDFSplitter().extract_pages(sample_pdf, [0, 2, 4], out)
        assert result.exists()

        # 验证页数
        import fitz
        doc = fitz.open(str(result))
        assert len(doc) == 3
        doc.close()

    def test_split_cancelled_early(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFSplitter, SplitOptions
        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        outputs = PDFSplitter().split_by_ranges(
            sample_pdf,
            [(0, 1), (2, 3)],
            options,
            should_cancel=lambda: True,
        )
        assert outputs == []

    def test_split_cancelled_cleanup_outputs(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFSplitter, SplitOptions
        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        calls = {"n": 0}

        def cancel_after_one():
            calls["n"] += 1
            return calls["n"] > 1

        outputs = PDFSplitter().split_by_ranges(
            sample_pdf,
            [(0, 0), (1, 1), (2, 2)],
            options,
            should_cancel=cancel_after_one,
            cleanup_on_cancel=True,
        )
        assert outputs == []
        assert list(tmp_path.glob("*_part*.pdf")) == []

    def test_split_by_blank_pages(self, tmp_path):
        pytest.importorskip("fitz")
        pytest.importorskip("pypdf")
        import fitz
        from core.pdf.processor import PDFSplitter, SplitOptions

        pdf_path = tmp_path / "blank_split.pdf"
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text(fitz.Point(72, 72), f"Chapter {i + 1}", fontsize=18)
            doc.new_page(width=595, height=842)  # blank separator
        doc.save(str(pdf_path))
        doc.close()

        options = SplitOptions(output_dir=tmp_path, overwrite=True)
        outputs = PDFSplitter().split_by_blank_pages(pdf_path, options)
        assert len(outputs) == 3
        assert all(p.exists() for p in outputs)


# ─────────────────────────────────────────────
# PDF 合并测试
# ─────────────────────────────────────────────

class TestPDFMerger:
    def test_merge(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFMerger, MergeOptions
        out = tmp_path / "merged.pdf"
        options = MergeOptions(output_path=out, overwrite=True, add_bookmarks=True)
        result = PDFMerger().merge([sample_pdf, sample_pdf], options)
        assert result.exists()

        import fitz
        doc = fitz.open(str(result))
        assert len(doc) == 10   # 5+5
        doc.close()

    def test_detect_duplicates(self, sample_pdf):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFMerger
        dups = PDFMerger().detect_duplicates([sample_pdf, sample_pdf])
        assert len(dups) == 1

    def test_merge_unify_page_size(self, tmp_path):
        pytest.importorskip("fitz")
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFMerger, MergeOptions
        import fitz
        from pypdf import PdfReader

        # 构造一个非 A4 尺寸的 PDF
        pdf1 = tmp_path / "w1.pdf"
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text(fitz.Point(50, 50), "W1", fontsize=20)
        doc.save(str(pdf1))
        doc.close()

        pdf2 = tmp_path / "w2.pdf"
        doc = fitz.open()
        page = doc.new_page(width=800, height=500)
        page.insert_text(fitz.Point(50, 50), "W2", fontsize=20)
        doc.save(str(pdf2))
        doc.close()

        out = tmp_path / "merged_a4.pdf"
        options = MergeOptions(
            output_path=out,
            overwrite=True,
            add_bookmarks=False,
            unify_page_size="A4",
            compress_output=False,
        )
        result = PDFMerger().merge([pdf1, pdf2], options)
        assert result.exists()

        reader = PdfReader(str(result))
        assert len(reader.pages) == 2
        for p in reader.pages:
            w = float(p.mediabox.width)
            h = float(p.mediabox.height)
            assert abs(w - 595.28) < 1.0
            assert abs(h - 841.89) < 1.0

    def test_merge_compress_output(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFMerger, MergeOptions
        out = tmp_path / "merged_compressed.pdf"
        options = MergeOptions(
            output_path=out,
            overwrite=True,
            add_bookmarks=False,
            unify_page_size=None,
            compress_output=True,
        )
        result = PDFMerger().merge([sample_pdf, sample_pdf], options)
        assert result.exists()
        assert result.stat().st_size > 0


# ─────────────────────────────────────────────
# PDF 压缩测试
# ─────────────────────────────────────────────

class TestPDFCompressor:
    def test_compress(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFCompressor, CompressOptions
        out = tmp_path / "compressed.pdf"
        options = CompressOptions(output_path=out, mode="balanced", overwrite=True)
        result = PDFCompressor().compress(sample_pdf, options)
        assert result.path.exists()
        assert result.compressed_size > 0

    def test_smart_compress(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFCompressor, CompressOptions
        out = tmp_path / "smart_compressed.pdf"
        options = CompressOptions(output_path=out, mode="smart", overwrite=True)
        result = PDFCompressor().compress(sample_pdf, options)
        assert result.path.exists()
        assert result.pages_preserved + result.pages_rasterized > 0


class TestPDFContentExtractor:
    def test_extract_text_combined(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFContentExtractor
        outputs = PDFContentExtractor().extract_text(sample_pdf, tmp_path, combined=True)
        assert len(outputs) == 1
        assert outputs[0].exists()

    def test_parse_page_range(self):
        from core.pdf.processor import PDFReader
        pages = PDFReader.parse_page_range("1-3,5", 10)
        assert pages == [0, 1, 2, 4]


class TestPDFPageEditor:
    def test_rotate_and_delete(self, sample_pdf, tmp_path):
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFPageEditor
        editor = PDFPageEditor()
        rotated = tmp_path / "rotated.pdf"
        editor.rotate_pages(sample_pdf, rotated, {0: 90})
        assert rotated.exists()
        deleted = tmp_path / "deleted.pdf"
        editor.delete_pages(sample_pdf, deleted, [0])
        from core.pdf.processor import PDFReader
        assert PDFReader.get_info(deleted).page_count == PDFReader.get_info(sample_pdf).page_count - 1

    def test_insert_blank_and_duplicate(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFPageEditor, PDFReader
        editor = PDFPageEditor()
        with_blank = tmp_path / "blank.pdf"
        editor.insert_blank_pages(sample_pdf, with_blank, after_page_index=0, count=2)
        assert PDFReader.get_info(with_blank).page_count == PDFReader.get_info(sample_pdf).page_count + 2

        dup = tmp_path / "dup.pdf"
        editor.duplicate_pages(sample_pdf, dup, [0])
        assert PDFReader.get_info(dup).page_count == PDFReader.get_info(sample_pdf).page_count + 1


class TestPDFEncrypt:
    def test_encrypt_dependencies_ready(self):
        from app.utils.deps import verify_core_dependencies
        missing = verify_core_dependencies()
        assert not missing, missing[0].install_hint if missing else ""

    def test_encrypt_decrypt(self, sample_pdf, tmp_path):
        pytest.importorskip("cryptography")
        pytest.importorskip("pypdf")
        from core.pdf.processor import PDFEncryptor, PDFReader
        enc = tmp_path / "enc.pdf"
        dec = tmp_path / "dec.pdf"
        PDFEncryptor().encrypt(sample_pdf, enc, user_password="secret")
        assert PDFReader.get_info(enc, password="secret").has_password
        PDFEncryptor().decrypt(enc, dec, password="secret")
        assert not PDFReader.get_info(dec).has_password


class TestPDFWatermark:
    def test_text_watermark_45deg(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFWatermarker, WatermarkOptions
        out = tmp_path / "wm.pdf"
        PDFWatermarker().add_text_watermark(
            sample_pdf, out,
            WatermarkOptions(text="Test", rotation=45, opacity=0.3),
        )
        assert out.exists() and out.stat().st_size > 0

    def test_text_watermark_cancelled_early(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.processor import PDFWatermarker, WatermarkOptions
        out = tmp_path / "wm_cancel.pdf"
        PDFWatermarker().add_text_watermark(
            sample_pdf,
            out,
            WatermarkOptions(text="Test", rotation=45, opacity=0.3),
            should_cancel=lambda: True,
        )
        assert out.exists() and out.stat().st_size > 0

    def test_image_watermark(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from PIL import Image
        from core.pdf.processor import PDFWatermarker, WatermarkOptions
        img = tmp_path / "wm.png"
        Image.new("RGBA", (120, 60), (255, 0, 0, 128)).save(img)
        out = tmp_path / "img_wm.pdf"
        PDFWatermarker().add_image_watermark(
            sample_pdf,
            out,
            WatermarkOptions(image_path=img, opacity=0.4, position="center"),
        )
        assert out.exists() and out.stat().st_size > 0


# ─────────────────────────────────────────────
# 阅读 / 批注测试
# ─────────────────────────────────────────────

class TestPDFViewer:
    def test_render_page(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.viewer import PDFViewerService
        png, w, h = PDFViewerService.render_page(sample_pdf, 0, zoom=1.0)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert w > 0 and h > 0

    def test_search_text(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.viewer import PDFViewerService
        hits = PDFViewerService.search_text(sample_pdf, " ")
        assert isinstance(hits, list)


class TestReaderZoom:
    def test_fit_width(self):
        from core.pdf.viewer import compute_reader_zoom, READER_FIT_H_MARGIN
        vw, vh = 800, 600
        pw, ph = 595.0, 842.0
        z = compute_reader_zoom(vw, vh, pw, ph, "fit_width")
        expected = (vw - READER_FIT_H_MARGIN) / pw
        assert abs(z - expected) < 0.001

    def test_fit_height(self):
        from core.pdf.viewer import compute_reader_zoom, READER_FIT_V_MARGIN
        vw, vh = 800, 600
        pw, ph = 595.0, 842.0
        z = compute_reader_zoom(vw, vh, pw, ph, "fit_height")
        expected = (vh - READER_FIT_V_MARGIN) / ph
        assert abs(z - expected) < 0.001

    def test_actual_size(self):
        from core.pdf.viewer import compute_reader_zoom
        z = compute_reader_zoom(800, 600, 595.0, 842.0, "actual")
        assert z == 1.0

    def test_fixed_clamped(self):
        from core.pdf.viewer import compute_reader_zoom, READER_ZOOM_MIN, READER_ZOOM_MAX
        assert compute_reader_zoom(800, 600, 595.0, 842.0, "fixed", fixed_zoom=10.0) == READER_ZOOM_MAX
        assert compute_reader_zoom(800, 600, 595.0, 842.0, "fixed", fixed_zoom=0.01) == READER_ZOOM_MIN


class TestTextSnap:
    def test_snap_selection_to_words(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.viewer import PDFViewerService
        rect = (0.0, 0.0, 500.0, 200.0)
        snapped = PDFViewerService.snap_selection_to_words(sample_pdf, 0, rect)
        assert snapped[0] <= snapped[2] and snapped[1] <= snapped[3]

    def test_snap_empty_returns_original(self, sample_pdf):
        pytest.importorskip("fitz")
        from core.pdf.viewer import PDFViewerService
        rect = (0.0, 0.0, 1.0, 1.0)
        snapped = PDFViewerService.snap_selection_to_words(sample_pdf, 0, rect)
        assert snapped == rect


class TestReaderRenderCache:
    def test_touch_evicts_oldest(self):
        from app.utils.render_cache import ReaderRenderCache
        cache = ReaderRenderCache(max_size=2)
        cache.touch(0, 1.0)
        cache.touch(1, 1.0)
        evicted = cache.touch(2, 1.0)
        assert evicted == [0]
        assert cache.is_valid(1, 1.0)
        assert cache.is_valid(2, 1.0)
        assert not cache.is_valid(0, 1.0)

    def test_zoom_change_invalidates(self):
        from app.utils.render_cache import ReaderRenderCache
        cache = ReaderRenderCache(max_size=4)
        cache.touch(0, 1.0)
        assert cache.is_valid(0, 1.0)
        assert not cache.is_valid(0, 1.5)

    def test_clear(self):
        from app.utils.render_cache import ReaderRenderCache
        cache = ReaderRenderCache(max_size=4)
        cache.touch(0, 1.0)
        cache.touch(1, 1.0)
        pages = cache.clear()
        assert sorted(pages) == [0, 1]
        assert len(cache) == 0


class TestPDFAnnotations:
    def test_save_highlight(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.annotations import AnnotationItem, PDFAnnotationService
        out = tmp_path / "annotated.pdf"
        rect = (50.0, 50.0, 200.0, 80.0)
        PDFAnnotationService().save_with_annotations(
            sample_pdf,
            out,
            [AnnotationItem(page_index=0, kind="highlight", rect=rect)],
        )
        assert out.exists()
        items = PDFAnnotationService().list_annotations(out)
        assert len(items) >= 1

    def test_save_freetext(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.annotations import AnnotationItem, PDFAnnotationService
        out = tmp_path / "note.pdf"
        PDFAnnotationService().save_with_annotations(
            sample_pdf,
            out,
            [AnnotationItem(
                page_index=0,
                kind="freetext",
                rect=(72.0, 72.0, 260.0, 120.0),
                content="测试批注",
            )],
        )
        assert out.exists()

    def test_save_with_delete_xrefs(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.annotations import AnnotationItem, PDFAnnotationService
        svc = PDFAnnotationService()
        mid = tmp_path / "with_highlight.pdf"
        rect = (50.0, 50.0, 200.0, 80.0)
        svc.save_with_annotations(
            sample_pdf, mid,
            [AnnotationItem(page_index=0, kind="highlight", rect=rect)],
        )
        items = svc.list_annotations(mid)
        assert items and items[0].xref
        out = tmp_path / "removed.pdf"
        svc.save_with_annotations(
            mid, out, [], delete_xrefs=[items[0].xref],
        )
        remaining = svc.list_annotations(out)
        assert len(remaining) == 0

    def test_save_strikeout_and_note(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.annotations import AnnotationItem, PDFAnnotationService
        out = tmp_path / "more_annots.pdf"
        PDFAnnotationService().save_with_annotations(
            sample_pdf,
            out,
            [
                AnnotationItem(0, "strikeout", (50.0, 50.0, 200.0, 80.0)),
                AnnotationItem(0, "note", (100.0, 100.0, 118.0, 118.0), content="便签"),
            ],
        )
        assert out.exists()
        items = PDFAnnotationService().list_annotations(out)
        kinds = {i.kind for i in items}
        assert "strikeout" in kinds
        assert "note" in kinds

    def test_export_summary(self, sample_pdf, tmp_path):
        from core.pdf.annotations import AnnotationItem, PDFAnnotationService
        out = tmp_path / "summary.txt"
        anns = [AnnotationItem(0, "highlight", (10, 10, 50, 20))]
        PDFAnnotationService().export_summary(anns, out)
        assert "高亮" in out.read_text(encoding="utf-8")


# ─────────────────────────────────────────────
# 图像转换测试
# ─────────────────────────────────────────────

class TestPDFToImage:
    def test_convert_png(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.image.converter import PDFToImageConverter, PDFToImageOptions
        options = PDFToImageOptions(
            output_dir=tmp_path,
            format="PNG",
            dpi=72,
            pages=[0, 1],
        )
        outputs = PDFToImageConverter().convert(sample_pdf, options)
        assert len(outputs) == 2
        assert all(p.suffix == ".png" for p in outputs)

    def test_convert_cancelled_early(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.image.converter import PDFToImageConverter, PDFToImageOptions
        options = PDFToImageOptions(output_dir=tmp_path, format="PNG", dpi=72)
        outputs = PDFToImageConverter().convert(
            sample_pdf,
            options,
            should_cancel=lambda: True,
        )
        assert outputs == []

    def test_convert_cancelled_cleanup_outputs(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.image.converter import PDFToImageConverter, PDFToImageOptions
        options = PDFToImageOptions(output_dir=tmp_path, format="PNG", dpi=72, pages=[0, 1, 2])
        calls = {"n": 0}

        def cancel_after_one():
            calls["n"] += 1
            return calls["n"] > 1

        outputs = PDFToImageConverter().convert(
            sample_pdf,
            options,
            should_cancel=cancel_after_one,
            cleanup_on_cancel=True,
        )
        assert outputs == []
        assert list(tmp_path.glob("*.png")) == []

    def test_pdf_to_long_image(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from PIL import Image
        from core.image.converter import PDFToImageConverter, PDFToImageOptions
        out = tmp_path / "long.png"
        options = PDFToImageOptions(output_dir=tmp_path, format="PNG", dpi=72, pages=[0, 1])
        PDFToImageConverter().pdf_to_long_image(sample_pdf, out, options)
        assert out.exists()
        img = Image.open(out)
        assert img.height > img.width
        img.close()


class TestImageToPDF:
    def test_convert(self, sample_image, tmp_path):
        pytest.importorskip("fitz")
        from core.image.converter import ImageToPDFConverter, ImageToPDFOptions
        out = tmp_path / "output.pdf"
        options = ImageToPDFOptions(output_path=out, page_size="A4")
        result = ImageToPDFConverter().convert([sample_image], options)
        assert result.exists()

        import fitz
        doc = fitz.open(str(result))
        assert len(doc) == 1
        doc.close()


class TestImageMerge:
    def test_vertical_merge(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image, ImageDraw
        from core.image.merger import ImageMerger, ImageMergeOptions

        paths = []
        for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
            p = tmp_path / f"img_{i}.png"
            img = Image.new("RGB", (100, 50 + i * 10), color)
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), str(i + 1), fill=(255, 255, 255))
            img.save(p)
            paths.append(p)

        options = ImageMergeOptions(
            output_dir=tmp_path,
            output_stem="vmerge",
            mode="vertical",
            format="PNG",
            spacing=4,
        )
        outputs = ImageMerger().merge(paths, options)
        assert len(outputs) == 1
        assert outputs[0].exists()
        out = Image.open(outputs[0])
        assert out.width == 100
        assert out.height == 50 + 60 + 70 + 4 * 2 + 0  # images + spacing
        out.close()

    def test_horizontal_merge(self, sample_image, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.merger import ImageMerger, ImageMergeOptions

        img2 = tmp_path / "img2.png"
        Image.open(sample_image).save(img2)
        options = ImageMergeOptions(
            output_dir=tmp_path,
            output_stem="hmerge",
            mode="horizontal",
            format="JPEG",
        )
        outputs = ImageMerger().merge([sample_image, img2], options)
        assert len(outputs) == 1
        assert outputs[0].suffix.lower() in (".jpg", ".jpeg")

    def test_grid_merge_pagination(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.merger import ImageMerger, ImageMergeOptions

        paths = []
        for i in range(5):
            p = tmp_path / f"g_{i}.png"
            Image.new("RGB", (40, 40), (i * 40, 100, 150)).save(p)
            paths.append(p)

        options = ImageMergeOptions(
            output_dir=tmp_path,
            output_stem="grid",
            mode="grid",
            grid_rows=2,
            grid_cols=2,
            margin=10,
            spacing=5,
        )
        outputs = ImageMerger().merge(paths, options)
        assert len(outputs) == 2
        for o in outputs:
            assert o.stat().st_size > 0

    def test_vertical_fixed_width(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.merger import ImageMerger, ImageMergeOptions

        paths = []
        for w in (80, 120):
            p = tmp_path / f"fw_{w}.png"
            Image.new("RGB", (w, 40), (200, 100, 50)).save(p)
            paths.append(p)

        options = ImageMergeOptions(
            output_dir=tmp_path,
            output_stem="fixed",
            mode="vertical",
            fixed_canvas_width=200,
        )
        outputs = ImageMerger().merge(paths, options)
        out = Image.open(outputs[0])
        assert out.width == 200
        out.close()

    def test_render_preview(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.merger import ImageMerger, ImageMergeOptions

        paths = []
        for i in range(3):
            p = tmp_path / f"pv_{i}.png"
            Image.new("RGB", (300, 200), (i * 60, 80, 120)).save(p)
            paths.append(p)

        options = ImageMergeOptions(output_dir=tmp_path, mode="vertical")
        preview = ImageMerger().render_preview(paths, options)
        assert max(preview.size) <= ImageMerger.PREVIEW_MAX_SIDE
        preview.close()

    def test_grid_page_suffix(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.merger import ImageMerger, ImageMergeOptions

        paths = []
        for i in range(5):
            p = tmp_path / f"s_{i}.png"
            Image.new("RGB", (30, 30), (100, 100, 100)).save(p)
            paths.append(p)

        options = ImageMergeOptions(
            output_dir=tmp_path,
            output_stem="album",
            mode="grid",
            grid_rows=2,
            grid_cols=2,
            page_suffix_template="-p{page}",
        )
        outputs = ImageMerger().merge(paths, options)
        names = {o.name for o in outputs}
        assert "album-p1.png" in names
        assert "album-p2.png" in names


class TestImageCompress:
    def test_scale_compress(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.compressor import ImageCompressor, ImageCompressOptions

        src = tmp_path / "big.png"
        Image.new("RGB", (800, 600), (120, 80, 200)).save(src)

        options = ImageCompressOptions(
            output_dir=tmp_path,
            mode="scale",
            scale_percent=50,
            output_format="JPEG",
            jpeg_quality=80,
        )
        result = ImageCompressor().compress_file(src, options)
        assert result.output_path.exists()
        assert result.compressed_size < result.original_size
        with Image.open(result.output_path) as out:
            assert out.width == 400
            assert out.height == 300

    def test_target_size_under_limit(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.compressor import ImageCompressor, ImageCompressOptions

        src = tmp_path / "photo.jpg"
        Image.new("RGB", (1200, 900), (50, 150, 220)).save(src, quality=95)

        target = 80 * 1024
        options = ImageCompressOptions(
            output_dir=tmp_path,
            mode="target_size",
            target_max_bytes=target,
            output_format="JPEG",
        )
        result = ImageCompressor().compress_file(src, options)
        assert result.compressed_size <= target
        assert result.quality_used is not None
        assert result.scale_used is not None

    def test_batch_compress(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from core.image.compressor import ImageCompressor, ImageCompressOptions

        paths = []
        for i in range(3):
            p = tmp_path / f"c_{i}.png"
            Image.new("RGB", (200, 150), (i * 40, 90, 120)).save(p)
            paths.append(p)

        out_dir = tmp_path / "out"
        options = ImageCompressOptions(
            output_dir=out_dir,
            mode="quality",
            jpeg_quality=60,
            output_format="JPEG",
        )
        results = ImageCompressor().compress_batch(paths, options)
        assert len(results) == 3
        for r in results:
            assert r.output_path.exists()


# ─────────────────────────────────────────────
# 拆分页 UI 回归测试
# ─────────────────────────────────────────────

class TestSplitPageMode:
    """回归：SegmentedWidget 应使用 currentRouteKey() 而非 currentItem()"""

    def test_segmented_route_key(self, qapp):
        from qfluentwidgets import SegmentedWidget

        seg = SegmentedWidget()
        seg.addItem("ranges", "自定义范围")
        seg.addItem("count", "按页数")
        seg.setCurrentItem("ranges")

        assert seg.currentRouteKey() == "ranges"
        # currentItem() 返回 PivotItem 控件，不能与 routeKey 字符串比较
        assert seg.currentItem() != "ranges"
        seg.setCurrentItem("count")
        assert seg.currentRouteKey() == "count"


# ─────────────────────────────────────────────
# OCR 引擎测试（依赖 rapidocr-onnxruntime）
# ─────────────────────────────────────────────

class TestOCR:
    def test_engine_availability(self):
        from core.ocr.engine import OCRManager
        manager = OCRManager()
        # 不强制要求安装，只检测接口
        assert hasattr(manager, "is_available")
        assert hasattr(manager, "ocr_pdf")
        assert hasattr(manager, "export_results")

    def test_export_txt(self, tmp_path):
        from core.ocr.engine import OCRManager, OCRResult, OCRBlock
        manager = OCRManager.__new__(OCRManager)
        results = [
            OCRResult(
                page_index=0,
                blocks=[OCRBlock(text="测试文字", confidence=0.95, bbox=(0, 0, 1, 1))],
                full_text="测试文字",
            )
        ]
        out = manager._export_txt(results, tmp_path / "output")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "测试文字" in content

    def test_export_json(self, tmp_path):
        import json
        from core.ocr.engine import OCRManager, OCRResult, OCRBlock
        manager = OCRManager.__new__(OCRManager)
        results = [
            OCRResult(
                page_index=0,
                blocks=[OCRBlock(text="hello", confidence=0.9, bbox=(0, 0, 0.5, 0.1))],
                full_text="hello",
            )
        ]
        out = manager._export_json(results, tmp_path / "output")
        data = json.loads(out.read_text())
        assert data[0]["full_text"] == "hello"

    def test_generate_searchable_pdf_roundtrip(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.ocr.engine import OCRManager, OCRResult, OCRBlock

        # 伪造 OCR 结果（测试生成可搜索 PDF 不崩）
        manager = OCRManager.__new__(OCRManager)
        # 注意：PyMuPDF 对中文 glyph 的 search_for 可能受 ToUnicode/字体影响而返回空；
        # 单测用 ASCII 文本验证“确实插入了可搜索文本层”更稳定。
        search_text = "SearchText"
        results = [
            OCRResult(
                page_index=0,
                blocks=[OCRBlock(text=search_text, confidence=0.9, bbox=(0.1, 0.1, 0.4, 0.2))],
                full_text=search_text,
            )
        ]
        out = tmp_path / "searchable.pdf"
        manager.generate_searchable_pdf(sample_pdf, results, out)
        assert out.exists() and out.stat().st_size > 0

        # 只校验文本层是否可被 search_for 命中
        import fitz
        doc = fitz.open(str(out))
        rects = doc[0].search_for(search_text)
        doc.close()
        assert len(rects) >= 1

    def test_ocr_pdf_cancelled_early(self, sample_pdf):
        from core.ocr.engine import OCRManager, OCROptions
        manager = OCRManager()
        if not manager.is_available:
            pytest.skip("OCR 引擎不可用")
        results = manager.ocr_pdf(
            sample_pdf,
            OCROptions(languages=["ch", "en"], dpi=100),
            should_cancel=lambda: True,
        )
        assert results == []

    def test_generate_searchable_pdf_cancel_cleanup(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.ocr.engine import OCRManager, OCRResult, OCRBlock

        manager = OCRManager.__new__(OCRManager)
        search_text = "SearchText"
        results = [
            OCRResult(
                page_index=0,
                blocks=[OCRBlock(text=search_text, confidence=0.9, bbox=(0.1, 0.1, 0.4, 0.2))],
                full_text=search_text,
            )
        ]
        out = tmp_path / "searchable_cancel.pdf"
        manager.generate_searchable_pdf(
            sample_pdf,
            results,
            out,
            should_cancel=lambda: True,
            cleanup_on_cancel=True,
        )
        assert not out.exists()


# ─────────────────────────────────────────────
# PDF 扩展工具测试（去水印 / 表单 / 签名）
# ─────────────────────────────────────────────

class TestPDFExtras:
    def test_redact_regions(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.extras import PDFRedactionService, RedactRegion
        out = tmp_path / "redacted.pdf"
        result = PDFRedactionService().apply_redactions(
            sample_pdf,
            out,
            regions=[RedactRegion(0, (50.0, 50.0, 200.0, 100.0))],
        )
        assert result.path.exists()
        assert result.redacted_regions >= 1

    def test_image_enhance_file(self, sample_image, tmp_path):
        pytest.importorskip("cv2")
        from core.image.converter import ImageEnhancer, ImageEnhanceOptions
        out = tmp_path / "enhanced.png"
        ImageEnhancer().enhance_file(
            sample_image, out,
            ImageEnhanceOptions(deskew=False, remove_border=False),
        )
        assert out.exists() and out.stat().st_size > 0

    def test_detect_repeated_text_watermark(self, tmp_path):
        pytest.importorskip("fitz")
        import fitz
        from core.pdf.extras import PDFWatermarkRemover

        pdf_path = tmp_path / "wm.pdf"
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_text(fitz.Point(72, 72), f"Page {i + 1}", fontsize=12)
            page.insert_text(fitz.Point(200, 400), "CONFIDENTIAL", fontsize=18)
        doc.save(str(pdf_path))
        doc.close()

        candidates = PDFWatermarkRemover().detect_candidates(pdf_path)
        text_keys = {c.key for c in candidates if c.kind == "text"}
        assert "CONFIDENTIAL" in text_keys

    def test_remove_text_watermark(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.extras import PDFWatermarkRemover
        out = tmp_path / "no_wm.pdf"
        result = PDFWatermarkRemover().remove(
            sample_pdf,
            out,
            text_patterns=["PDF Studio Unit Test"],
        )
        assert result.path.exists()
        assert result.removed_text_blocks >= 1

    def test_form_list_and_fill(self, tmp_path):
        pytest.importorskip("fitz")
        import fitz
        from core.pdf.extras import PDFFormService

        pdf_path = tmp_path / "form.pdf"
        doc = fitz.open()
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = "username"
        widget.field_value = ""
        widget.rect = fitz.Rect(72, 72, 300, 96)
        page.add_widget(widget)
        doc.save(str(pdf_path))
        doc.close()

        fields = PDFFormService().list_fields(pdf_path)
        assert any(f.name == "username" for f in fields)

        out = tmp_path / "filled.pdf"
        PDFFormService().fill(pdf_path, out, {"username": "Alice"})
        filled = PDFFormService().list_fields(out)
        assert next(f for f in filled if f.name == "username").value == "Alice"

    def test_pdf_compare(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.compare import PDFCompareService
        import fitz

        pdf_b = tmp_path / "variant.pdf"
        doc = fitz.open(str(sample_pdf))
        page = doc[0]
        page.insert_text(fitz.Point(300, 300), "Extra", fontsize=12)
        doc.save(str(pdf_b))
        doc.close()

        result = PDFCompareService().compare(sample_pdf, pdf_b)
        assert result.page_count_a == result.page_count_b
        assert result.text_match_rate < 1.0
        assert any(not d.match for d in result.text_diffs)

    def test_pdf_compare_encrypted_requires_password(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.compare import PDFCompareService
        from core.pdf.processor import PDFEncryptor

        enc = tmp_path / "enc.pdf"
        PDFEncryptor().encrypt(sample_pdf, enc, user_password="secret")
        with pytest.raises(ValueError, match="密码"):
            PDFCompareService().compare(sample_pdf, enc)
        result = PDFCompareService().compare(
            sample_pdf, enc, password_b="secret"
        )
        assert result.pages_compared >= 1

    def test_pdf_compare_render_fallback_on_blank_pages(self, tmp_path):
        pytest.importorskip("fitz")
        import fitz
        from core.pdf.compare import PDFCompareService

        a = tmp_path / "blank_a.pdf"
        b = tmp_path / "blank_b.pdf"
        for path in (a, b):
            doc = fitz.open()
            doc.new_page(width=200, height=200)
            doc.save(str(path))
            doc.close()

        result = PDFCompareService().compare(a, b)
        assert result.text_match_rate == 1.0
        assert result.text_diffs[0].compare_mode == "render"

    def test_image_signature(self, sample_pdf, sample_image, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.extras import PDFSignatureService, SignatureOptions
        out = tmp_path / "signed.pdf"
        options = SignatureOptions(image_path=sample_image, page_index=0)
        PDFSignatureService().add_image_signature(sample_pdf, out, options)
        assert out.exists() and out.stat().st_size > sample_pdf.stat().st_size

    def test_text_overlay(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        from core.pdf.extras import PDFTextOverlayService, TextOverlayItem
        out = tmp_path / "typed.pdf"
        PDFTextOverlayService().add_text_overlays(
            sample_pdf,
            out,
            [TextOverlayItem(0, (72, 72, 300, 120), "Overlay Text", font_size=14)],
        )
        assert out.exists()

    def test_metadata_update(self, sample_pdf, tmp_path):
        pytest.importorskip("fitz")
        import fitz
        from core.pdf.extras import PDFMetadataService
        out = tmp_path / "meta.pdf"
        PDFMetadataService().update_metadata(
            sample_pdf, out, title="Test Title", author="Tester"
        )
        doc = fitz.open(str(out))
        assert doc.metadata.get("title") == "Test Title"
        assert doc.metadata.get("author") == "Tester"
        doc.close()


class TestWeb:
    def test_url_to_pdf_cancelled_early_cleanup(self, tmp_path):
        from core.web.processor import WebProcessor, WebToPDFOptions

        processor = WebProcessor()
        out = tmp_path / "web_cancel.pdf"
        options = WebToPDFOptions(output_path=out)

        result = processor.url_to_pdf(
            "https://example.com",
            options,
            should_cancel=lambda: True,
            cleanup_on_cancel=True,
        )

        assert result == out
        assert not out.exists()


class TestExtendedSettings:
    def test_web_and_workflow_defaults(self):
        from app.config.settings import AppSettings

        s = AppSettings()
        assert s.web.scroll_wait == 0.5
        assert s.web.max_scroll_times == 20
        assert s.web.print_background is True
        assert s.workflow.auto_retry_on_failure is True
        assert s.workflow.retry_count == 3
        assert s.workflow.queue_max_size == 100
        assert s.web.batch_concurrency == 2

    def test_workflow_history_store(self, monkeypatch, tmp_path):
        from app.config.settings import SettingsManager
        from app.utils.workflow_history import WorkflowHistoryStore

        monkeypatch.setattr(SettingsManager, "CONFIG_DIR", tmp_path)
        mgr = SettingsManager.get_instance()
        s = mgr.settings
        s.workflow.save_workflow_history = True
        wf = {"compress_enabled": True, "compress_mode": "balanced", "encrypt_password": "secret"}
        results = [{"file": "a.pdf", "error": None}, {"file": "b.pdf", "error": "x"}]
        WorkflowHistoryStore.append_from_run(wf, str(tmp_path / "out"), 2, results)
        entries = WorkflowHistoryStore.load()
        assert len(entries) == 1
        assert entries[0].success_count == 1
        assert entries[0].workflow.get("encrypt_password") == ""
        s.workflow.save_workflow_history = False
        WorkflowHistoryStore.append_from_run(wf, str(tmp_path / "out2"), 1, results[:1])
        assert len(WorkflowHistoryStore.load()) == 1

    def test_workflow_history_from_run_steps(self):
        from app.utils.workflow_history import WorkflowHistoryEntry

        entry = WorkflowHistoryEntry.from_run(
            {
                "ocr_enabled": True,
                "compress_enabled": True,
                "watermark_enabled": False,
            },
            "/tmp/out",
            3,
            [{"error": None}, {"error": None}],
        )
        assert "OCR" in entry.steps_summary
        assert "压缩" in entry.steps_summary

    def test_ocr_model_paths_serialization(self):
        from app.config.settings import AppSettings

        s = AppSettings()
        s.ocr.det_model_path = "/models/det.onnx"
        s.ocr.rec_model_path = "/models/rec.onnx"
        s.ocr.use_gpu = True
        s2 = AppSettings.model_validate_json(s.model_dump_json())
        assert s2.ocr.det_model_path == "/models/det.onnx"
        assert s2.ocr.use_gpu is True

    def test_reader_settings_defaults(self):
        from app.config.settings import AppSettings, ReaderSettings

        s = AppSettings()
        assert s.reader.fit_mode == "fit_width"
        assert s.reader.layout_mode == "single"
        assert s.reader.sidebar_width == 240
        rs = ReaderSettings(fixed_zoom=1.5, layout_mode="dual")
        s2 = AppSettings.model_validate_json(
            AppSettings(reader=rs).model_dump_json()
        )
        assert s2.reader.fixed_zoom == 1.5
        assert s2.reader.layout_mode == "dual"


class TestRetryHelper:
    def test_run_with_retry_success(self):
        from app.utils.retry import run_with_retry

        calls = {"n": 0}

        def work():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("transient")
            return "ok"

        assert run_with_retry(work, max_attempts=3) == "ok"
        assert calls["n"] == 2

    def test_run_with_retry_exhausted(self):
        from app.utils.retry import run_with_retry

        def always_fail():
            raise RuntimeError("always")

        with pytest.raises(RuntimeError, match="always"):
            run_with_retry(always_fail, max_attempts=2)


class TestOCREngineConfig:
    def test_rapidocr_kwargs_from_settings(self, tmp_path):
        from app.config.settings import OCRSettings
        from core.ocr.engine import RapidOCREngine

        model = tmp_path / "det.onnx"
        model.write_bytes(b"x")
        cfg = OCRSettings(det_model_path=str(model), use_gpu=True)
        kwargs = RapidOCREngine(cfg)._build_rapidocr_kwargs()
        assert kwargs["det_model_path"] == str(model)
        assert kwargs["det_use_cuda"] is True

    def test_rapidocr_skips_missing_model_path(self):
        from app.config.settings import OCRSettings
        from core.ocr.engine import RapidOCREngine

        cfg = OCRSettings(det_model_path="/nonexistent/det.onnx")
        kwargs = RapidOCREngine(cfg)._build_rapidocr_kwargs()
        assert "det_model_path" not in kwargs


class TestBatchWorkflow:
    def test_workflow_max_attempts_respects_settings(self, monkeypatch):
        from app.config.settings import AppSettings, SettingsManager
        from app.pages import batch_page

        s = AppSettings()
        s.workflow.auto_retry_on_failure = False
        s.workflow.retry_count = 5
        mgr = SettingsManager.__new__(SettingsManager)
        mgr._settings = s
        monkeypatch.setattr(batch_page, "settings_mgr", mgr)
        assert batch_page._workflow_max_attempts() == 1

        s.workflow.auto_retry_on_failure = True
        assert batch_page._workflow_max_attempts() == 5


class TestTaskHub:
    def test_queue_when_at_concurrency_limit(self, qapp):
        from app.utils.task_hub import TaskHub
        from app.workers.base_worker import BaseWorker

        class DummyWorker(BaseWorker):
            def run_task(self):
                return None

        hub = TaskHub.__new__(TaskHub)
        QObject = __import__("PyQt6.QtCore", fromlist=["QObject"]).QObject
        QObject.__init__(hub)
        hub._tasks = {}
        hub._wait_queue = __import__("collections").deque()
        hub._counter = 0
        TaskHub._instance = hub

        started: list[str] = []

        def fake_start(task_id: str, worker) -> None:
            started.append(task_id)
            hub._tasks[task_id].status = "running"
            hub.tasksChanged.emit()

        hub._start_task = fake_start

        w1 = DummyWorker()
        w2 = DummyWorker()
        assert hub.submit(w1, "任务A", max_concurrent=1, max_total=5) is True
        assert hub.submit(w2, "任务B", max_concurrent=1, max_total=5) is True
        assert len(started) == 1
        assert hub.running_count() == 1
        assert hub.queued_count() == 1
        assert hub.wait_queue_length() == 1

        hub._set_status(started[0], "done")
        hub._dispatch_next(1, 5)
        assert hub.running_count() == 1
        assert hub.queued_count() == 0
        assert len(started) == 2

    def test_reject_when_queue_full(self, qapp):
        from app.utils.task_hub import TaskHub
        from app.workers.base_worker import BaseWorker

        class DummyWorker(BaseWorker):
            def run_task(self):
                return None

        hub = TaskHub.__new__(TaskHub)
        QObject = __import__("PyQt6.QtCore", fromlist=["QObject"]).QObject
        QObject.__init__(hub)
        hub._tasks = {}
        hub._wait_queue = __import__("collections").deque()
        hub._counter = 0
        TaskHub._instance = hub

        for i in range(2):
            rec = hub._register(DummyWorker(), f"占位{i}")
            hub._tasks[rec].status = "running"

        rejected = hub.submit(DummyWorker(), "溢出任务", max_concurrent=2, max_total=2)
        assert rejected is False
        assert hub.total_active() == 2

    def test_submit_worker_returns_bool(self, qapp, monkeypatch):
        from app.config.settings import AppSettings, SettingsManager
        from app.utils.task_hub import TaskHub
        from app.workers.base_worker import BaseWorker, submit_worker

        class QuickWorker(BaseWorker):
            def run_task(self):
                return "ok"

        s = AppSettings()
        s.workflow.max_workers = 1
        s.workflow.queue_max_size = 1
        mgr = SettingsManager.__new__(SettingsManager)
        mgr._settings = s
        monkeypatch.setattr("app.config.settings.settings_mgr", mgr)

        hub = TaskHub.__new__(TaskHub)
        QObject = __import__("PyQt6.QtCore", fromlist=["QObject"]).QObject
        QObject.__init__(hub)
        hub._tasks = {}
        hub._wait_queue = __import__("collections").deque()
        hub._counter = 0
        TaskHub._instance = hub

        def fake_start(task_id: str, worker) -> None:
            hub._tasks[task_id].status = "running"

        hub._start_task = fake_start

        w1 = QuickWorker()
        w2 = QuickWorker()
        assert submit_worker(w1, "A") is True
        assert submit_worker(w2, "B") is False
