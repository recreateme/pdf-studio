"""
PDF Studio - 扩展 PDF 工具（去水印 / 表单 / 签名）
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import fitz

from app.utils.logger import logger


@dataclass
class RedactRegion:
    """涂黑区域（PDF 坐标 pt）"""
    page_index: int
    rect: tuple[float, float, float, float]


@dataclass
class RedactResult:
    path: Path
    redacted_regions: int = 0
    redacted_text_blocks: int = 0


@dataclass
class WatermarkCandidate:
    """检测到的疑似水印"""
    kind: str
    key: str
    label: str
    page_count: int
    total_pages: int


@dataclass
class WatermarkRemoveResult:
    path: Path
    removed_images: int = 0
    removed_text_blocks: int = 0


@dataclass
class FormFieldInfo:
    """PDF 表单字段"""
    name: str
    field_type: str
    value: str
    page_index: int
    choices: list[str] = field(default_factory=list)


@dataclass
class SignatureOptions:
    """图片签名选项"""
    image_path: Path
    page_index: int = -1
    width: float = 120.0
    height: float = 48.0
    margin_x: float = 36.0
    margin_y: float = 36.0
    position: str = "bottom_right"


class PDFWatermarkRemover:
    """有限场景水印检测与移除"""

    def detect_candidates(
        self,
        path: str | Path,
        password: str = "",
        *,
        min_page_ratio: float = 0.3,
    ) -> list[WatermarkCandidate]:
        """
        检测疑似水印：
        - 在多页重复出现的相同内嵌图片
        - 在多页重复出现的相同短文本
        """
        path = Path(path)
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        total = len(doc)
        xref_pages: dict[int, set[int]] = defaultdict(set)
        text_pages: dict[str, set[int]] = defaultdict(set)

        for i in range(total):
            page = doc[i]
            for img in page.get_images(full=True):
                xref_pages[img[0]].add(i)
            blocks = page.get_text("blocks")
            for block in blocks:
                if len(block) < 5:
                    continue
                text = str(block[4]).strip()
                if len(text) < 2 or len(text) > 80:
                    continue
                text_pages[text].add(i)

        doc.close()
        min_pages = max(2, int(total * min_page_ratio))
        candidates: list[WatermarkCandidate] = []

        for xref, pages in xref_pages.items():
            if len(pages) >= min_pages:
                candidates.append(WatermarkCandidate(
                    kind="image",
                    key=str(xref),
                    label=f"内嵌图片 xref={xref}（出现在 {len(pages)}/{total} 页）",
                    page_count=len(pages),
                    total_pages=total,
                ))

        for text, pages in text_pages.items():
            if len(pages) >= min_pages:
                preview = text if len(text) <= 40 else text[:37] + "..."
                candidates.append(WatermarkCandidate(
                    kind="text",
                    key=text,
                    label=f"重复文字「{preview}」（{len(pages)}/{total} 页）",
                    page_count=len(pages),
                    total_pages=total,
                ))

        candidates.sort(key=lambda c: (-c.page_count, c.kind))
        return candidates

    def remove(
        self,
        path: str | Path,
        output_path: str | Path,
        *,
        image_xrefs: Optional[list[int]] = None,
        text_patterns: Optional[list[str]] = None,
        password: str = "",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> WatermarkRemoveResult:
        """按选中的图片 xref 与文字模式移除水印"""
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        image_xrefs = set(image_xrefs or [])
        text_patterns = [t.strip() for t in (text_patterns or []) if t.strip()]

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        removed_images = 0
        removed_text = 0
        total = len(doc)

        for i, page in enumerate(doc):
            if image_xrefs:
                for img in page.get_images(full=True):
                    xref = img[0]
                    if xref in image_xrefs:
                        try:
                            page.delete_image(xref)
                            removed_images += 1
                        except Exception as e:
                            logger.warning(f"删除图片 xref={xref} 失败: {e}")

            if text_patterns:
                for pattern in text_patterns:
                    for rect in page.search_for(pattern):
                        page.add_redact_annot(rect, fill=(1, 1, 1))
                        removed_text += 1
                if text_patterns:
                    page.apply_redactions()

            if progress_cb:
                progress_cb(i + 1, total)

        doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        doc.close()
        logger.info(
            f"去水印完成: 图片 {removed_images} 处, 文字块 {removed_text} 处"
        )
        return WatermarkRemoveResult(
            path=output_path,
            removed_images=removed_images,
            removed_text_blocks=removed_text,
        )


class PDFFormService:
    """AcroForm 表单读取与填写"""

    def list_fields(
        self,
        path: str | Path,
        password: str = "",
    ) -> list[FormFieldInfo]:
        path = Path(path)
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        fields: list[FormFieldInfo] = []
        for i in range(len(doc)):
            page = doc[i]
            for widget in page.widgets() or []:
                name = widget.field_name or f"field_p{i+1}_{len(fields)}"
                ftype = widget.field_type_string or "unknown"
                value = widget.field_value or ""
                choices: list[str] = []
                try:
                    if widget.choice_values:
                        choices = list(widget.choice_values)
                except Exception:
                    pass
                fields.append(FormFieldInfo(
                    name=name,
                    field_type=ftype,
                    value=str(value) if value is not None else "",
                    page_index=i,
                    choices=choices,
                ))
        doc.close()
        return fields

    def fill(
        self,
        path: str | Path,
        output_path: str | Path,
        field_values: dict[str, str],
        password: str = "",
    ) -> Path:
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        filled = 0
        for i in range(len(doc)):
            page = doc[i]
            for widget in page.widgets() or []:
                name = widget.field_name
                if not name or name not in field_values:
                    continue
                widget.field_value = field_values[name]
                widget.update()
                filled += 1

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"表单填写完成: {filled} 个字段 -> {output_path.name}")
        return output_path


class PDFRedactionService:
    """PDF 永久涂黑 / 敏感信息脱敏"""

    def apply_redactions(
        self,
        path: str | Path,
        output_path: str | Path,
        *,
        regions: Optional[list[RedactRegion]] = None,
        text_patterns: Optional[list[str]] = None,
        password: str = "",
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> RedactResult:
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        regions = list(regions or [])
        text_patterns = [t.strip() for t in (text_patterns or []) if t.strip()]

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        region_count = 0
        text_count = 0
        total = len(doc)

        regions_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for r in regions:
            regions_by_page.setdefault(r.page_index, []).append(r.rect)

        for i, page in enumerate(doc):
            for rect in regions_by_page.get(i, []):
                page.add_redact_annot(fitz.Rect(*rect), fill=(0, 0, 0))
                region_count += 1
            for pattern in text_patterns:
                for found in page.search_for(pattern):
                    page.add_redact_annot(found, fill=(0, 0, 0))
                    text_count += 1
            if regions_by_page.get(i) or text_patterns:
                page.apply_redactions()
            if progress_cb:
                progress_cb(i + 1, total)

        doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        doc.close()
        logger.info(
            f"涂黑完成: 区域 {region_count} 处, 文字 {text_count} 处 -> {output_path.name}"
        )
        return RedactResult(
            path=output_path,
            redacted_regions=region_count,
            redacted_text_blocks=text_count,
        )


@dataclass
class TextOverlayItem:
    """打字机文本块"""
    page_index: int
    rect: tuple[float, float, float, float]
    text: str
    font_size: float = 12.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


class PDFTextOverlayService:
    """在 PDF 页面上叠加文字（打字机，非改原文字）"""

    def add_text_overlays(
        self,
        path: str | Path,
        output_path: str | Path,
        items: list[TextOverlayItem],
        password: str = "",
    ) -> Path:
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        for item in items:
            if not item.text.strip():
                continue
            page_index = max(0, min(item.page_index, len(doc) - 1))
            page = doc[page_index]
            rc = page.insert_textbox(
                fitz.Rect(*item.rect),
                item.text,
                fontsize=item.font_size,
                color=item.color,
                align=fitz.TEXT_ALIGN_LEFT,
            )
            if rc < 0:
                logger.warning(f"第 {page_index + 1} 页文字可能溢出文本框")

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"已叠加 {len(items)} 处文字 -> {output_path.name}")
        return output_path


class PDFMetadataService:
    """PDF 文档元数据读写"""

    def update_metadata(
        self,
        path: str | Path,
        output_path: str | Path,
        *,
        title: str = "",
        author: str = "",
        subject: str = "",
        keywords: str = "",
        password: str = "",
    ) -> Path:
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        meta = dict(doc.metadata or {})
        if title:
            meta["title"] = title
        if author:
            meta["author"] = author
        if subject:
            meta["subject"] = subject
        if keywords:
            meta["keywords"] = keywords
        doc.set_metadata(meta)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"元数据已更新 -> {output_path.name}")
        return output_path


class PDFSignatureService:
    """图片/手绘签名（插入 PDF，非 CA 数字证书）"""

    POSITIONS = {
        "bottom_right": lambda w, h, sw, sh, mx, my: (w - sw - mx, h - sh - my),
        "bottom_left": lambda w, h, sw, sh, mx, my: (mx, h - sh - my),
        "bottom_center": lambda w, h, sw, sh, mx, my: ((w - sw) / 2, h - sh - my),
    }

    def add_image_signature(
        self,
        path: str | Path,
        output_path: str | Path,
        options: SignatureOptions,
        password: str = "",
    ) -> Path:
        if not options.image_path.is_file():
            raise ValueError("签名图片不存在")

        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        page_index = options.page_index
        if page_index < 0:
            page_index = len(doc) - 1
        page_index = max(0, min(page_index, len(doc) - 1))
        page = doc[page_index]
        rect = page.rect

        pos_fn = self.POSITIONS.get(options.position, self.POSITIONS["bottom_right"])
        x, y = pos_fn(
            rect.width, rect.height,
            options.width, options.height,
            options.margin_x, options.margin_y,
        )
        target = fitz.Rect(x, y, x + options.width, y + options.height)
        page.insert_image(target, filename=str(options.image_path), overlay=True)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"签名已插入第 {page_index + 1} 页 -> {output_path.name}")
        return output_path
