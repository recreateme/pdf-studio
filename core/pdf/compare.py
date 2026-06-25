"""
PDF Studio - PDF 轻量对比
页数 / 体积 / 元数据 / 逐页文本 diff（扫描页可选渲染抽样）
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import fitz

from app.utils.logger import logger


@dataclass
class PageTextDiff:
    page_index: int
    text_a: str
    text_b: str
    match: bool
    compare_mode: str = "text"  # text | render
    note: str = ""


@dataclass
class PDFCompareOptions:
    """对比选项"""
    normalize_whitespace: bool = True
    compare_metadata: bool = True
    render_fallback_dpi: int = 72
    max_detail_pages: int = 20


@dataclass
class PDFCompareResult:
    path_a: Path
    path_b: Path
    page_count_a: int
    page_count_b: int
    size_a: int
    size_b: int
    page_count_match: bool
    size_diff_pct: float
    pages_compared: int
    text_match_count: int
    encrypted_a: bool = False
    encrypted_b: bool = False
    metadata_lines: list[str] = field(default_factory=list)
    metadata_match: bool = True
    text_diffs: list[PageTextDiff] = field(default_factory=list)
    cancelled: bool = False

    @property
    def text_match_rate(self) -> float:
        if not self.pages_compared:
            return 0.0
        return self.text_match_count / self.pages_compared

    @property
    def is_mostly_match(self) -> bool:
        return self.page_count_match and self.text_match_rate >= 0.99

    def summary_lines(self) -> list[str]:
        lines = [
            f"文件 A：{self.path_a.name}  ·  {self.page_count_a} 页  ·  {self.size_a:,} B"
            + ("  · 已加密" if self.encrypted_a else ""),
            f"文件 B：{self.path_b.name}  ·  {self.page_count_b} 页  ·  {self.size_b:,} B"
            + ("  · 已加密" if self.encrypted_b else ""),
            f"页数一致：{'是' if self.page_count_match else '否'}",
        ]
        if not self.page_count_match:
            extra_a = max(0, self.page_count_a - self.pages_compared)
            extra_b = max(0, self.page_count_b - self.pages_compared)
            if extra_a:
                lines.append(f"仅 A 多出的页：{extra_a} 页（第 {self.pages_compared + 1}～{self.page_count_a} 页）")
            if extra_b:
                lines.append(f"仅 B 多出的页：{extra_b} 页（第 {self.pages_compared + 1}～{self.page_count_b} 页）")

        lines.extend([
            f"体积差异：{self.size_diff_pct:+.1f}%",
            f"内容对比：{self.text_match_count}/{self.pages_compared} 页一致 "
            f"({self.text_match_rate * 100:.0f}%)",
        ])

        if self.metadata_lines:
            lines.append("")
            lines.append("文档信息：")
            lines.extend(f"  {line}" for line in self.metadata_lines)

        diff_pages = [d for d in self.text_diffs if not d.match]
        if diff_pages:
            lines.append("")
            lines.append(f"不一致的页（前 {min(len(diff_pages), self._detail_limit())} 处）：")
            for d in diff_pages[: self._detail_limit()]:
                mode = "渲染" if d.compare_mode == "render" else "文本"
                lines.append(f"  第 {d.page_index + 1} 页（{mode}）")
                if d.note:
                    lines.append(f"    {d.note}")
                if d.text_a or d.text_b:
                    if d.text_a:
                        lines.append(f"    A: {d.text_a[:120]}")
                    if d.text_b:
                        lines.append(f"    B: {d.text_b[:120]}")

        if self.cancelled:
            lines.append("")
            lines.append("（对比已取消，结果为部分页）")

        return lines

    def _detail_limit(self) -> int:
        return 20


def _normalize_text(text: str, *, normalize: bool) -> str:
    text = text or ""
    if normalize:
        return " ".join(text.split())
    return text.strip()


def _page_render_hash(page: fitz.Page, dpi: int) -> str:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    digest = hashlib.md5(pix.samples).hexdigest()
    return digest


def _open_pdf(path: Path, password: str, label: str) -> fitz.Document:
    if not path.exists():
        raise FileNotFoundError(f"{label} 不存在: {path}")
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise ValueError(f"无法打开 {label}: {e}") from e

    if doc.is_encrypted:
        if not password:
            doc.close()
            raise ValueError(f"{label} 已加密，请输入打开密码")
        if not doc.authenticate(password):
            doc.close()
            raise ValueError(f"{label} 密码错误")
    elif doc.needs_pass:
        doc.close()
        raise ValueError(f"{label} 需要密码才能打开")

    return doc


class PDFCompareService:
    """PDF 轻量对比服务"""

    def compare(
        self,
        path_a: str | Path,
        path_b: str | Path,
        password_a: str = "",
        password_b: str = "",
        options: Optional[PDFCompareOptions] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> PDFCompareResult:
        opts = options or PDFCompareOptions()
        path_a = Path(path_a)
        path_b = Path(path_b)

        size_a = path_a.stat().st_size
        size_b = path_b.stat().st_size
        size_diff_pct = (
            (size_b - size_a) / size_a * 100.0 if size_a else 0.0
        )

        doc_a = _open_pdf(path_a, password_a, "文件 A")
        doc_b = _open_pdf(path_b, password_b, "文件 B")

        try:
            count_a = len(doc_a)
            count_b = len(doc_b)
            compare_pages = min(count_a, count_b)

            meta_lines, meta_match = self._compare_metadata(
                doc_a, doc_b, opts.compare_metadata
            )

            diffs: list[PageTextDiff] = []
            match_count = 0
            cancelled = False

            for i in range(compare_pages):
                if should_cancel and should_cancel():
                    cancelled = True
                    break

                page_a = doc_a[i]
                page_b = doc_b[i]
                text_a = _normalize_text(page_a.get_text(), normalize=opts.normalize_whitespace)
                text_b = _normalize_text(page_b.get_text(), normalize=opts.normalize_whitespace)

                if text_a or text_b:
                    same = text_a == text_b
                    mode = "text"
                    note = ""
                else:
                    hash_a = _page_render_hash(page_a, opts.render_fallback_dpi)
                    hash_b = _page_render_hash(page_b, opts.render_fallback_dpi)
                    same = hash_a == hash_b
                    mode = "render"
                    note = "无文字层，已按低分辨率渲染抽样对比" if not same else "无文字层，渲染抽样一致"

                if same:
                    match_count += 1

                diffs.append(
                    PageTextDiff(
                        page_index=i,
                        text_a=text_a[:200],
                        text_b=text_b[:200],
                        match=same,
                        compare_mode=mode,
                        note=note,
                    )
                )

                if progress_cb:
                    progress_cb(i + 1, compare_pages)

            result = PDFCompareResult(
                path_a=path_a,
                path_b=path_b,
                page_count_a=count_a,
                page_count_b=count_b,
                size_a=size_a,
                size_b=size_b,
                page_count_match=count_a == count_b,
                size_diff_pct=size_diff_pct,
                pages_compared=len(diffs),
                text_match_count=match_count,
                encrypted_a=bool(password_a) or doc_a.is_encrypted,
                encrypted_b=bool(password_b) or doc_b.is_encrypted,
                metadata_lines=meta_lines,
                metadata_match=meta_match,
                text_diffs=diffs,
                cancelled=cancelled,
            )
            logger.info(
                f"PDF 对比完成: {path_a.name} vs {path_b.name} "
                f"({match_count}/{len(diffs)} 页一致)"
            )
            return result
        finally:
            doc_a.close()
            doc_b.close()

    @staticmethod
    def _compare_metadata(
        doc_a: fitz.Document,
        doc_b: fitz.Document,
        enabled: bool,
    ) -> tuple[list[str], bool]:
        if not enabled:
            return [], True

        keys = ("title", "author", "subject", "creator", "producer")
        meta_a = doc_a.metadata or {}
        meta_b = doc_b.metadata or {}
        lines: list[str] = []
        all_match = True

        for key in keys:
            val_a = (meta_a.get(key) or "").strip()
            val_b = (meta_b.get(key) or "").strip()
            if val_a == val_b:
                continue
            all_match = False
            label = {"title": "标题", "author": "作者", "subject": "主题"}.get(key, key)
            lines.append(f"{label}：A「{val_a or '（空）'}」 vs B「{val_b or '（空）'}」")

        if all_match:
            lines.append("元数据字段一致")
        return lines, all_match
