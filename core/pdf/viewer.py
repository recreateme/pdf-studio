"""
PDF Studio - 阅读与搜索
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz

from app.utils.logger import logger


@dataclass
class SearchHit:
    """全文搜索结果"""
    page_index: int
    rect: tuple[float, float, float, float]
    snippet: str


READER_ZOOM_MIN = 0.25
READER_ZOOM_MAX = 4.0
READER_FIT_H_MARGIN = 32
READER_FIT_V_MARGIN = 80


def compute_reader_zoom(
    viewport_width: int,
    viewport_height: int,
    page_width: float,
    page_height: float,
    mode: str,
    *,
    fixed_zoom: float = 1.0,
) -> float:
    """
    计算阅读器有效缩放比。

    mode: fit_width | fit_height | actual | fixed
    """
    if mode == "fit_width" and page_width > 0:
        usable = max(1, viewport_width - READER_FIT_H_MARGIN)
        return max(READER_ZOOM_MIN, min(READER_ZOOM_MAX, usable / page_width))
    if mode == "fit_height" and page_height > 0:
        usable = max(1, viewport_height - READER_FIT_V_MARGIN)
        return max(READER_ZOOM_MIN, min(READER_ZOOM_MAX, usable / page_height))
    if mode == "actual":
        return 1.0
    return max(READER_ZOOM_MIN, min(READER_ZOOM_MAX, fixed_zoom))


class PDFViewerService:
    """PDF 渲染与全文搜索"""

    @staticmethod
    def render_page(
        path: str | Path,
        page_index: int,
        zoom: float = 1.0,
        password: str = "",
    ) -> tuple[bytes, float, float]:
        """
        渲染页面为 PNG。

        Returns:
            (png_bytes, page_width_pt, page_height_pt)
        """
        zoom = max(0.25, min(zoom, 4.0))
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)
        page = doc[page_index]
        rect = page.rect
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        data = pix.tobytes("png")
        doc.close()
        return data, rect.width, rect.height

    @staticmethod
    def search_text(
        path: str | Path,
        query: str,
        password: str = "",
        *,
        max_hits: int = 200,
    ) -> list[SearchHit]:
        """全文搜索，返回命中列表"""
        query = query.strip()
        if not query:
            return []

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        hits: list[SearchHit] = []
        for i in range(len(doc)):
            page = doc[i]
            for rect in page.search_for(query):
                if len(hits) >= max_hits:
                    break
                snippet = page.get_textbox(rect).strip() or query
                hits.append(SearchHit(
                    page_index=i,
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                    snippet=snippet[:120],
                ))
            if len(hits) >= max_hits:
                break

        doc.close()
        logger.debug(f"搜索 \"{query}\" -> {len(hits)} 处命中")
        return hits

    @staticmethod
    def page_text(path: str | Path, page_index: int, password: str = "") -> str:
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)
        text = doc[page_index].get_text()
        doc.close()
        return text

    @staticmethod
    def snap_selection_to_words(
        path: str | Path,
        page_index: int,
        rect: tuple[float, float, float, float],
        password: str = "",
    ) -> tuple[float, float, float, float]:
        """将框选区域吸附到与选区相交的文字块外接矩形。"""
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)
        if not 0 <= page_index < len(doc):
            doc.close()
            return rect
        page = doc[page_index]
        sel = fitz.Rect(*rect)
        merged = None
        for word in page.get_text("words"):
            wr = fitz.Rect(word[0], word[1], word[2], word[3])
            if wr.intersects(sel):
                merged = wr if merged is None else merged | wr
        doc.close()
        if merged is None:
            return rect
        return (merged.x0, merged.y0, merged.x1, merged.y1)
