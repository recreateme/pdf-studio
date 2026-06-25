"""
打包冒烟：在无 GUI 下验证核心 PDF 链路与依赖（供 main.py --pack-smoke 与 scripts/pack_smoke.py 调用）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def _make_sample_pdf(path: Path, pages: int = 5) -> Path:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            fitz.Point(72, 72),
            f"Pack Smoke Page {i + 1}",
            fontsize=20,
        )
    doc.save(str(path))
    doc.close()
    return path


def smoke_result_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "pack_smoke_result.txt"


def _write_smoke_result(message: str, *, ok: bool) -> None:
    smoke_result_path().write_text(f"{'OK' if ok else 'FAIL'}: {message}\n", encoding="utf-8")
    print(message)


def run_pack_smoke() -> int:
    """执行核心链路检查，成功返回 0。"""
    from app.utils.deps import format_missing_dependencies_message, verify_core_dependencies
    from app.utils.logger import setup_logger, logger

    setup_logger()
    logger.info("pack-smoke 开始 (frozen=%s)", getattr(sys, "frozen", False))

    missing = verify_core_dependencies()
    if missing:
        msg = format_missing_dependencies_message(missing)
        _write_smoke_result(msg, ok=False)
        print(msg, file=sys.stderr)
        return 2

    try:
        _run_pack_smoke_checks()
    except Exception as exc:
        _write_smoke_result(str(exc), ok=False)
        raise

    logger.info("pack-smoke 全部通过")
    _write_smoke_result("PACK_SMOKE_OK", ok=True)
    return 0


def _run_pack_smoke_checks() -> None:
    import shutil

    from core.pdf.compare import PDFCompareService
    from core.pdf.processor import (
        CompressOptions,
        MergeOptions,
        PDFCompressor,
        PDFEncryptor,
        PDFMerger,
        PDFReader,
        PDFSplitter,
        PDFWatermarker,
        SplitOptions,
        WatermarkOptions,
    )

    with tempfile.TemporaryDirectory(prefix="pdf_studio_pack_smoke_") as td:
        work = Path(td)
        src = _make_sample_pdf(work / "sample.pdf")

        split_dir = work / "split"
        split_dir.mkdir()
        parts = PDFSplitter().split_by_count(
            src,
            2,
            SplitOptions(output_dir=split_dir, overwrite=True),
        )
        assert len(parts) >= 2, "拆分应至少 2 个文件"
        for p in parts:
            assert p.stat().st_size > 0

        merged = work / "merged.pdf"
        PDFMerger().merge(
            parts[:2],
            MergeOptions(output_path=merged, overwrite=True, add_bookmarks=False),
        )
        assert PDFReader.get_info(merged).page_count == PDFReader.get_info(parts[0]).page_count + PDFReader.get_info(
            parts[1]
        ).page_count

        compressed = work / "compressed.pdf"
        PDFCompressor().compress(
            src,
            CompressOptions(output_path=compressed, mode="balanced", overwrite=True),
        )
        assert compressed.exists() and compressed.stat().st_size > 0

        enc = work / "encrypted.pdf"
        dec = work / "decrypted.pdf"
        PDFEncryptor().encrypt(src, enc, user_password="test123")
        PDFEncryptor().decrypt(enc, dec, password="test123")
        assert dec.exists() and dec.stat().st_size > 0

        wm = work / "watermarked.pdf"
        PDFWatermarker().add_text_watermark(
            src,
            wm,
            WatermarkOptions(text="PDF Studio", rotation=45, opacity=0.3),
        )
        assert wm.stat().st_size > 0

        copy = work / "sample_copy.pdf"
        shutil.copy2(src, copy)
        cmp = PDFCompareService().compare(src, copy)
        assert cmp.page_count_match and cmp.page_count_a == 5
