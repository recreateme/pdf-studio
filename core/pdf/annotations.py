"""
PDF Studio - PDF 批注（高亮 / 下划线 / 删除线 / 文本 / 便签 / 图章 / 手绘 / 形状）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz

from app.utils.logger import logger


STAMP_NAMES = {
    "Approved": fitz.STAMP_Approved,
    "AsIs": fitz.STAMP_AsIs,
    "Confidential": fitz.STAMP_Confidential,
    "Departmental": fitz.STAMP_Departmental,
    "Draft": fitz.STAMP_Draft,
    "Experimental": fitz.STAMP_Experimental,
    "Expired": fitz.STAMP_Expired,
    "Final": fitz.STAMP_Final,
    "ForComment": fitz.STAMP_ForComment,
    "ForPublicRelease": fitz.STAMP_ForPublicRelease,
    "NotApproved": fitz.STAMP_NotApproved,
    "NotForPublicRelease": fitz.STAMP_NotForPublicRelease,
    "Sold": fitz.STAMP_Sold,
    "TopSecret": fitz.STAMP_TopSecret,
}


@dataclass
class AnnotationItem:
    """已有或待保存的批注项"""
    page_index: int
    kind: str
    rect: tuple[float, float, float, float]
    content: str = ""
    color: tuple[float, float, float] = (1.0, 1.0, 0.0)
    points: list[tuple[float, float]] = field(default_factory=list)
    stamp_name: str = "Approved"
    xref: int = 0


@dataclass
class AnnotationSession:
    """内存中的批注会话（保存前）"""
    source_path: Path
    pending: list[AnnotationItem] = field(default_factory=list)


class PDFAnnotationService:
    """PDF 标准批注读写"""

    HIGHLIGHT_COLOR = (1.0, 1.0, 0.0)
    UNDERLINE_COLOR = (1.0, 0.0, 0.0)
    STRIKE_COLOR = (1.0, 0.0, 0.0)
    TEXT_COLOR = (0.0, 0.0, 0.0)
    INK_COLOR = (0.0, 0.0, 1.0)
    RECT_COLOR = (1.0, 0.0, 0.0)

    def list_annotations(
        self,
        path: str | Path,
        password: str = "",
    ) -> list[AnnotationItem]:
        """读取 PDF 内已有批注"""
        path = Path(path)
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        items: list[AnnotationItem] = []
        for i in range(len(doc)):
            page = doc[i]
            for annot in page.annots() or []:
                kind = self._map_annot_type(annot.type[1] if annot.type else "")
                if not kind:
                    continue
                rect = annot.rect
                item = AnnotationItem(
                    page_index=i,
                    kind=kind,
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                    content=annot.info.get("content", "") or annot.info.get("subject", ""),
                    xref=getattr(annot, "xref", 0) or 0,
                )
                if kind == "ink":
                    try:
                        item.points = [
                            (p.x, p.y) for p in annot.vertices or []
                        ]
                    except Exception:
                        pass
                items.append(item)
        doc.close()
        return items

    @staticmethod
    def _map_annot_type(type_name: str) -> Optional[str]:
        mapping = {
            "Highlight": "highlight",
            "Underline": "underline",
            "StrikeOut": "strikeout",
            "FreeText": "freetext",
            "Text": "note",
            "Stamp": "stamp",
            "Ink": "ink",
            "Square": "rect",
            "Line": "line",
        }
        return mapping.get(type_name)

    def save_with_annotations(
        self,
        path: str | Path,
        output_path: str | Path,
        annotations: list[AnnotationItem],
        password: str = "",
        delete_xrefs: list[int] | None = None,
    ) -> Path:
        """将批注写入 PDF 并保存到新文件（可选删除已有批注）"""
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)

        if delete_xrefs:
            to_delete = set(delete_xrefs)
            for page in doc:
                for annot in list(page.annots() or []):
                    if getattr(annot, "xref", 0) in to_delete:
                        page.delete_annot(annot)

        for ann in annotations:
            if not 0 <= ann.page_index < len(doc):
                continue
            page = doc[ann.page_index]
            rect = fitz.Rect(*ann.rect)
            a = None
            if ann.kind == "highlight":
                a = page.add_highlight_annot(rect)
                a.set_colors(stroke=ann.color or self.HIGHLIGHT_COLOR)
                a.set_opacity(0.4)
            elif ann.kind == "underline":
                a = page.add_underline_annot(rect)
                a.set_colors(stroke=ann.color or self.UNDERLINE_COLOR)
            elif ann.kind == "strikeout":
                a = page.add_strikeout_annot(rect)
                a.set_colors(stroke=ann.color or self.STRIKE_COLOR)
            elif ann.kind == "freetext":
                a = page.add_freetext_annot(
                    rect,
                    ann.content or "批注",
                    fontsize=12,
                    text_color=self.TEXT_COLOR,
                    fill_color=(1, 1, 0.85),
                )
            elif ann.kind == "note":
                pt = fitz.Point(rect.x0, rect.y0)
                a = page.add_text_annot(pt, ann.content or "便签")
                a.set_info(content=ann.content or "便签")
            elif ann.kind == "stamp":
                stamp_id = STAMP_NAMES.get(ann.stamp_name, fitz.STAMP_Approved)
                a = page.add_stamp_annot(rect, stamp=stamp_id)
            elif ann.kind == "ink" and ann.points:
                pts = [fitz.Point(x, y) for x, y in ann.points]
                a = page.add_ink_annot([pts])
                a.set_colors(stroke=ann.color or self.INK_COLOR)
                a.set_border(width=1.5)
            elif ann.kind == "rect":
                a = page.add_rect_annot(rect)
                a.set_colors(stroke=ann.color or self.RECT_COLOR)
                a.set_border(width=1.5)
            elif ann.kind == "line":
                p1 = fitz.Point(rect.x0, rect.y0)
                p2 = fitz.Point(rect.x1, rect.y1)
                a = page.add_line_annot(p1, p2)
                a.set_colors(stroke=ann.color or self.RECT_COLOR)
                a.set_border(width=1.5)
            if a is not None:
                a.update()

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(
            f"批注已保存: {output_path.name} "
            f"(+{len(annotations)} / -{len(delete_xrefs or [])})"
        )
        return output_path

    def export_summary(
        self,
        annotations: list[AnnotationItem],
        output_path: str | Path,
    ) -> Path:
        """导出批注摘要为文本"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        kind_labels = {
            "highlight": "高亮",
            "underline": "下划线",
            "strikeout": "删除线",
            "freetext": "文本框",
            "note": "便签",
            "stamp": "图章",
            "ink": "手绘",
            "rect": "矩形",
            "line": "线条",
        }
        lines = [f"批注摘要 · 共 {len(annotations)} 条", ""]
        for i, ann in enumerate(annotations, 1):
            label = kind_labels.get(ann.kind, ann.kind)
            text = ann.content or ann.stamp_name or label
            lines.append(f"{i}. 第 {ann.page_index + 1} 页 · {label} · {text}")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path
