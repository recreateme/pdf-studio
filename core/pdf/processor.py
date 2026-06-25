"""
PDF Studio - PDF 核心处理引擎
提供拆分、合并、压缩、加密、水印等 PDF 操作
依赖：PyMuPDF (fitz) + pypdf
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import fitz                          # PyMuPDF
from pypdf import PdfReader, PdfWriter

from app.utils.logger import logger
from app.utils.helpers import get_unique_path, make_temp_file


# ─────────────────────────────────────────────
# 数据类型
# ─────────────────────────────────────────────

@dataclass
class PDFPageInfo:
    """单页信息"""
    index: int                       # 0-based页码
    width: float                     # 页宽 (pt)
    height: float                    # 页高 (pt)
    rotation: int = 0                # 旋转角度
    has_text: bool = True            # 是否含文字层
    label: str = ""                  # 页面标签


@dataclass
class PDFInfo:
    """PDF文档信息"""
    path: Path
    page_count: int
    file_size: int                   # bytes
    title: str = ""
    author: str = ""
    creator: str = ""
    has_password: bool = False
    bookmarks: list[dict] = field(default_factory=list)
    pages: list[PDFPageInfo] = field(default_factory=list)


@dataclass
class SplitOptions:
    """拆分选项"""
    output_dir: Path
    mode: str = "pages"              # pages / size / bookmark / blank
    pages_per_file: int = 1          # mode=pages 时每份页数
    max_size_mb: float = 10.0        # mode=size 时最大MB
    custom_ranges: list[tuple[int, int]] = field(default_factory=list)
    name_template: str = "{stem}_part{index:03d}"
    overwrite: bool = False


@dataclass
class MergeOptions:
    """合并选项"""
    output_path: Path
    add_bookmarks: bool = True       # 用文件名生成书签
    unify_page_size: Optional[str] = None   # None/A4/Letter
    add_cover_page: Optional[Path] = None
    compress_output: bool = False
    overwrite: bool = False


@dataclass
class CompressOptions:
    """压缩选项"""
    output_path: Path
    mode: str = "balanced"           # high_quality/balanced/max_compress/smart
    image_dpi: int = 150
    jpeg_quality: int = 75
    remove_metadata: bool = False
    overwrite: bool = False
    smart_text_threshold: int = 50   # mode=smart 时，超过该字符数的页保留文字层


@dataclass
class CompressResult:
    """压缩结果统计"""
    path: Path
    original_size: int
    compressed_size: int
    pages_preserved: int = 0
    pages_rasterized: int = 0

    @property
    def savings_ratio(self) -> float:
        if self.original_size <= 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100


@dataclass
class WatermarkOptions:
    """水印选项"""
    text: str = ""
    image_path: Optional[Path] = None
    opacity: float = 0.3
    rotation: float = 45.0
    font_size: int = 48
    color: tuple[float, float, float] = (0.5, 0.5, 0.5)
    position: str = "center"        # center/tile
    pages: Optional[list[int]] = None   # None=全部页
    image_scale: float = 1.0        # 图片水印缩放（相对原始尺寸）


@dataclass
class PageNumberOptions:
    """页码选项"""
    position: str = "bottom_center"  # bottom_center/bottom_right/etc.
    start_page: int = 1
    start_number: int = 1
    skip_first: bool = False
    font_size: int = 12
    margin: float = 20.0
    format_str: str = "{n}"         # {n}=页码 {total}=总页数


# ─────────────────────────────────────────────
# PDF 信息读取
# ─────────────────────────────────────────────

class PDFReader:
    """PDF文档信息与内容读取器"""

    @staticmethod
    def get_info(path: str | Path, password: str = "") -> PDFInfo:
        """
        读取 PDF 元信息

        Args:
            path: PDF 文件路径
            password: 解密密码（加密PDF需要）

        Returns:
            PDFInfo 数据对象

        Raises:
            ValueError: 文件格式错误或密码错误
            FileNotFoundError: 文件不存在
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"无法打开PDF: {e}") from e

        # 处理加密PDF
        has_password = doc.is_encrypted
        if has_password:
            if not password:
                doc.close()
                raise ValueError("PDF已加密，请提供密码")
            if not doc.authenticate(password):
                doc.close()
                raise ValueError("密码错误")

        meta = doc.metadata or {}
        bookmarks = PDFReader._extract_bookmarks(doc)
        pages_info = []

        for i in range(len(doc)):
            page = doc[i]
            rect = page.rect
            pages_info.append(PDFPageInfo(
                index=i,
                width=rect.width,
                height=rect.height,
                rotation=page.rotation,
                has_text=bool(page.get_text().strip()),
            ))

        info = PDFInfo(
            path=path,
            page_count=len(doc),
            file_size=path.stat().st_size,
            title=meta.get("title", ""),
            author=meta.get("author", ""),
            creator=meta.get("creator", ""),
            has_password=has_password,
            bookmarks=bookmarks,
            pages=pages_info,
        )
        doc.close()
        logger.debug(f"读取PDF信息: {path.name}, {info.page_count}页")
        return info

    @staticmethod
    def _extract_bookmarks(doc: fitz.Document) -> list[dict]:
        """提取书签/目录"""
        toc = doc.get_toc()
        return [
            {"level": lvl, "title": title, "page": page - 1}
            for lvl, title, page in toc
        ]

    @staticmethod
    def render_page(
        path: str | Path,
        page_index: int,
        dpi: int = 150,
        password: str = "",
    ) -> bytes:
        """
        渲染指定页为 PNG 字节数据

        Args:
            path: PDF路径
            page_index: 0-based页码
            dpi: 渲染分辨率

        Returns:
            PNG 格式字节数据
        """
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)
        page = doc[page_index]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        data = pix.tobytes("png")
        doc.close()
        return data

    @staticmethod
    def render_thumbnail(
        path: str | Path,
        page_index: int,
        width: int = 160,
        password: str = "",
    ) -> bytes:
        """渲染缩略图，指定宽度自动等比缩放"""
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.authenticate(password)
        page = doc[page_index]
        rect = page.rect
        scale = width / rect.width
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        data = pix.tobytes("png")
        doc.close()
        return data

    @staticmethod
    def parse_page_range(spec: str, page_count: int) -> list[int]:
        """
        解析页码范围字符串为 0-based 索引列表。

        例：\"1-3,5,7-9\" -> [0,1,2,4,6,7,8]
        """
        spec = spec.strip()
        if not spec:
            return []
        indices: set[int] = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                start = max(1, int(a.strip()))
                end = min(page_count, int(b.strip()))
                for p in range(start, end + 1):
                    indices.add(p - 1)
            else:
                p = int(part)
                if 1 <= p <= page_count:
                    indices.add(p - 1)
        return sorted(indices)


# ─────────────────────────────────────────────
# PDF 内容提取
# ─────────────────────────────────────────────

class PDFContentExtractor:
    """PDF 文字与内嵌图片提取"""

    def extract_text(
        self,
        path: str | Path,
        output_dir: str | Path,
        page_indices: Optional[list[int]] = None,
        *,
        combined: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Path]:
        """提取 PDF 文字层为 TXT 文件"""
        path = Path(path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total_pages = len(doc)
        indices = page_indices if page_indices is not None else list(range(total_pages))
        indices = [i for i in indices if 0 <= i < total_pages]
        outputs: list[Path] = []

        if combined:
            parts: list[str] = []
            for n, i in enumerate(indices):
                parts.append(f"--- 第 {i + 1} 页 ---")
                parts.append(doc[i].get_text())
                if progress_cb:
                    progress_cb(n + 1, len(indices))
            out = output_dir / f"{path.stem}_text.txt"
            out.write_text("\n\n".join(parts), encoding="utf-8")
            outputs.append(out)
        else:
            for n, i in enumerate(indices):
                out = output_dir / f"{path.stem}_p{i + 1:04d}.txt"
                out.write_text(doc[i].get_text(), encoding="utf-8")
                outputs.append(out)
                if progress_cb:
                    progress_cb(n + 1, len(indices))

        doc.close()
        logger.info(f"文字提取完成: {len(outputs)} 个文件")
        return outputs

    def extract_images(
        self,
        path: str | Path,
        output_dir: str | Path,
        page_indices: Optional[list[int]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Path]:
        """提取 PDF 内嵌图片"""
        path = Path(path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total_pages = len(doc)
        indices = page_indices if page_indices is not None else list(range(total_pages))
        indices = [i for i in indices if 0 <= i < total_pages]
        outputs: list[Path] = []
        seen_xrefs: set[int] = set()

        for n, i in enumerate(indices):
            page = doc[i]
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    base = doc.extract_image(xref)
                except Exception as e:
                    logger.warning(f"提取图片失败 (页{i + 1}, xref={xref}): {e}")
                    continue
                ext = base.get("ext", "png")
                out = output_dir / f"{path.stem}_p{i + 1:04d}_img{img_idx + 1:02d}.{ext}"
                out.write_bytes(base["image"])
                outputs.append(out)
            if progress_cb:
                progress_cb(n + 1, len(indices))

        doc.close()
        logger.info(f"图片提取完成: {len(outputs)} 张")
        return outputs


# ─────────────────────────────────────────────
# PDF 拆分引擎
# ─────────────────────────────────────────────

class PDFSplitter:
    """PDF 拆分引擎"""

    def split_by_ranges(
        self,
        path: str | Path,
        ranges: list[tuple[int, int]],
        options: SplitOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """
        按页面范围拆分

        Args:
            path: 源PDF路径
            ranges: [(start, end), ...] 0-based，含两端
            options: 拆分选项
            progress_cb: 进度回调 (current, total)

        Returns:
            生成的PDF文件路径列表
        """
        path = Path(path)
        outputs = []
        reader = PdfReader(str(path))
        total = len(ranges)
        cancelled = False

        for idx, (start, end) in enumerate(ranges):
            if should_cancel and should_cancel():
                cancelled = True
                break
            writer = PdfWriter()
            for pg in range(start, end + 1):
                if 0 <= pg < len(reader.pages):
                    writer.add_page(reader.pages[pg])

            name = options.name_template.format(
                stem=path.stem,
                index=idx + 1,
                start=start + 1,
                end=end + 1,
            )
            out_path = options.output_dir / f"{name}.pdf"
            if not options.overwrite:
                out_path = get_unique_path(out_path)

            options.output_dir.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                writer.write(f)

            outputs.append(out_path)
            logger.info(f"已输出: {out_path.name} (页 {start+1}-{end+1})")

            if progress_cb:
                progress_cb(idx + 1, total)

        if cancelled and cleanup_on_cancel:
            for p in outputs:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            return []
        return outputs

    def split_by_count(
        self,
        path: str | Path,
        pages_per_file: int,
        options: SplitOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """按固定页数拆分"""
        info = PDFReader.get_info(path)
        n = info.page_count
        ranges = [
            (i, min(i + pages_per_file - 1, n - 1))
            for i in range(0, n, pages_per_file)
        ]
        return self.split_by_ranges(
            path, ranges, options, progress_cb, should_cancel, cleanup_on_cancel
        )

    def split_by_bookmarks(
        self,
        path: str | Path,
        options: SplitOptions,
        level: int = 1,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """
        按书签（目录）拆分

        Args:
            path: 源PDF
            options: 拆分选项
            level: 书签层级（1=顶层，2=二级，...）
        """
        info = PDFReader.get_info(path)
        bookmarks = [b for b in info.bookmarks if b["level"] <= level]

        if not bookmarks:
            raise ValueError("PDF中未找到书签，无法按书签拆分")

        # 构造范围
        ranges = []
        titles = []
        for i, bm in enumerate(bookmarks):
            start = bm["page"]
            end = bookmarks[i + 1]["page"] - 1 if i + 1 < len(bookmarks) else info.page_count - 1
            if start <= end:
                ranges.append((start, end))
                titles.append(bm["title"])

        # 覆盖命名模板以使用书签标题
        original_template = options.name_template
        outputs = []
        reader = PdfReader(str(path))
        cancelled = False

        for idx, ((start, end), title) in enumerate(zip(ranges, titles)):
            if should_cancel and should_cancel():
                cancelled = True
                break
            writer = PdfWriter()
            for pg in range(start, end + 1):
                if 0 <= pg < len(reader.pages):
                    writer.add_page(reader.pages[pg])

            from app.utils.helpers import safe_filename
            safe_title = safe_filename(title)[:50]
            name = f"{idx + 1:03d}_{safe_title}"
            out_path = options.output_dir / f"{name}.pdf"
            if not options.overwrite:
                out_path = get_unique_path(out_path)

            options.output_dir.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                writer.write(f)

            outputs.append(out_path)
            if progress_cb:
                progress_cb(idx + 1, len(ranges))

        if cancelled and cleanup_on_cancel:
            for p in outputs:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            return []
        return outputs

    def split_by_size(
        self,
        path: str | Path,
        max_size_mb: float,
        options: SplitOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """
        按文件大小拆分（估算模式）

        使用二分法近似拆分，实际输出大小可能略有偏差。
        """
        info = PDFReader.get_info(path)
        avg_page_size = info.file_size / max(info.page_count, 1)
        pages_per_file = max(1, int((max_size_mb * 1024 * 1024) / avg_page_size))

        options_copy = SplitOptions(
            output_dir=options.output_dir,
            mode="pages",
            pages_per_file=pages_per_file,
            name_template=options.name_template,
            overwrite=options.overwrite,
        )
        return self.split_by_count(
            path, pages_per_file, options_copy, progress_cb, should_cancel, cleanup_on_cancel
        )

    @staticmethod
    def _is_blank_page(doc: fitz.Document, page_index: int) -> bool:
        """判断页面是否为空白分隔页（无文字、无图片、无矢量绘制）"""
        page = doc[page_index]
        if page.get_text().strip():
            return False
        if page.get_images(full=True):
            return False
        if page.get_drawings():
            return False
        return True

    def split_by_blank_pages(
        self,
        path: str | Path,
        options: SplitOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """按空白页拆分（空白页作为章节分隔符，不会输出到结果中）"""
        path = Path(path)
        doc = fitz.open(str(path))
        total_pages = len(doc)
        blank_pages = {
            i for i in range(total_pages) if self._is_blank_page(doc, i)
        }
        doc.close()

        ranges: list[tuple[int, int]] = []
        start: Optional[int] = None
        for i in range(total_pages):
            if i in blank_pages:
                if start is not None:
                    ranges.append((start, i - 1))
                    start = None
            elif start is None:
                start = i
        if start is not None:
            ranges.append((start, total_pages - 1))

        if not ranges:
            raise ValueError("未检测到空白分隔页，无法按空白页拆分")

        return self.split_by_ranges(
            path, ranges, options, progress_cb, should_cancel, cleanup_on_cancel
        )

    def extract_pages(
        self,
        path: str | Path,
        page_indices: list[int],
        output_path: str | Path,
    ) -> Path:
        """
        提取指定页面为新PDF

        Args:
            path: 源PDF
            page_indices: 0-based页码列表
            output_path: 输出路径
        """
        output_path = Path(output_path)
        reader = PdfReader(str(path))
        writer = PdfWriter()

        for pg in sorted(set(page_indices)):
            if 0 <= pg < len(reader.pages):
                writer.add_page(reader.pages[pg])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(f"提取 {len(page_indices)} 页 -> {output_path.name}")
        return output_path


# ─────────────────────────────────────────────
# PDF 合并引擎
# ─────────────────────────────────────────────

class PDFMerger:
    """PDF 合并引擎"""

    def merge(
        self,
        paths: list[str | Path],
        options: MergeOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        """
        合并多个PDF

        Args:
            paths: 源PDF路径列表（顺序即合并顺序）
            options: 合并选项
            progress_cb: 进度回调

        Returns:
            合并后PDF路径
        """
        paths = [Path(p) for p in paths]
        output_path = Path(options.output_path)

        # 输出文件：若不允许覆盖则自动生成唯一文件名
        if not options.overwrite:
            output_path = get_unique_path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 若启用压缩：先合并到临时文件，再用 PDFCompressor 输出最终文件
        merged_path: Path = output_path
        tmp_merged: Optional[Path] = None
        if options.compress_output:
            tmp_merged = output_path.with_name(f"{output_path.stem}_merged_tmp.pdf")
            if tmp_merged.exists() and not options.overwrite:
                tmp_merged = get_unique_path(tmp_merged)
            merged_path = tmp_merged
            merged_path.parent.mkdir(parents=True, exist_ok=True)

        writer = PdfWriter()
        total = len(paths)
        cancelled = False

        for idx, pdf_path in enumerate(paths):
            if should_cancel and should_cancel():
                cancelled = True
                break
            try:
                reader = PdfReader(str(pdf_path))
                # 书签：用文件名作为顶层书签
                if options.add_bookmarks:
                    bookmark_page = len(writer.pages)
                    writer.add_outline_item(pdf_path.stem, bookmark_page)

                for page in reader.pages:
                    if options.unify_page_size:
                        page = self._resize_page(page, options.unify_page_size)
                    writer.add_page(page)

                logger.debug(f"已合并: {pdf_path.name} ({len(reader.pages)} 页)")
            except Exception as e:
                logger.error(f"合并 {pdf_path.name} 失败: {e}")

            if progress_cb:
                progress_cb(idx + 1, total)

        if cancelled and cleanup_on_cancel:
            if tmp_merged:
                try:
                    tmp_merged.unlink(missing_ok=True)
                except Exception:
                    pass
            return output_path

        with open(merged_path, "wb") as f:
            writer.write(f)

        # 可选：合并后压缩
        if options.compress_output:
            compressed = PDFCompressor().compress(
                merged_path,
                CompressOptions(
                    output_path=output_path,
                    mode="balanced",
                    overwrite=True,  # final output 已唯一生成，不应再追加后缀
                ),
                should_cancel=should_cancel,
                cleanup_on_cancel=cleanup_on_cancel,
            )
            if tmp_merged:
                try:
                    tmp_merged.unlink(missing_ok=True)
                except Exception:
                    pass
            logger.info(
                f"合并完成（已压缩） -> {compressed.path.name}，共 {len(writer.pages)} 页"
            )
            return compressed.path

        logger.info(f"合并完成 -> {output_path.name}，共 {len(writer.pages)} 页")
        return output_path

    def _resize_page(self, page, size: str):
        """统一页面尺寸（按目标尺寸缩放内容）"""
        SIZE_MAP = {
            "A4": (595.28, 841.89),
            "Letter": (612.0, 792.0),
            "A3": (841.89, 1190.55),
        }
        if size not in SIZE_MAP:
            return page

        target_w, target_h = SIZE_MAP[size]
        # pypdf 的 scale_to 会同时更新页面尺寸并对内容进行等比缩放
        # 若某些 PDF 页面对象不兼容缩放，则回退到仅调整框尺寸。
        try:
            page.scale_to(target_w, target_h)
        except Exception:
            # fallback: 仅改 mediabox/cropbox，不保证内容完全适配
            try:
                page.mediabox.upper_right = (target_w, target_h)
                if hasattr(page, "cropbox") and page.cropbox is not None:
                    page.cropbox.upper_right = (target_w, target_h)
            except Exception:
                pass
        return page

    def detect_duplicates(self, paths: list[str | Path]) -> list[tuple[Path, Path]]:
        """
        检测重复PDF（基于MD5）

        Returns:
            [(path1, path2), ...] 重复对列表
        """
        from app.utils.helpers import file_md5
        md5_map: dict[str, Path] = {}
        duplicates = []

        for p in paths:
            p = Path(p)
            md5 = file_md5(p)
            if md5 in md5_map:
                duplicates.append((md5_map[md5], p))
            else:
                md5_map[md5] = p

        return duplicates


# ─────────────────────────────────────────────
# PDF 压缩引擎
# ─────────────────────────────────────────────

class PDFCompressor:
    """PDF 压缩引擎"""

    PRESETS = {
        "high_quality": {"image_dpi": 150, "jpeg_quality": 85, "remove_meta": False},
        "balanced":     {"image_dpi": 120, "jpeg_quality": 72, "remove_meta": False},
        "max_compress": {"image_dpi": 96,  "jpeg_quality": 55, "remove_meta": True},
        "smart":        {"image_dpi": 120, "jpeg_quality": 72, "remove_meta": False},
    }

    def compress(
        self,
        path: str | Path,
        options: CompressOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> CompressResult:
        """
        压缩 PDF

        策略：
        - balanced/high_quality/max_compress：逐页栅格化
        - smart：含足够文字层的页面原样保留，其余页面栅格化

        Returns:
            CompressResult（含路径与体积统计）
        """
        path = Path(path)
        output_path = Path(options.output_path)
        if not options.overwrite:
            output_path = get_unique_path(output_path)

        preset = self.PRESETS.get(options.mode, self.PRESETS["balanced"])
        dpi = options.image_dpi or preset["image_dpi"]
        quality = options.jpeg_quality or preset["jpeg_quality"]
        remove_meta = options.remove_metadata or preset.get("remove_meta", False)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        orig_size = path.stat().st_size

        if options.mode == "smart":
            result_path, preserved, rasterized = self._compress_smart(
                path,
                output_path,
                dpi,
                quality,
                options.smart_text_threshold,
                progress_cb,
                should_cancel,
                cleanup_on_cancel,
            )
        else:
            result_path, preserved, rasterized = self._compress_rasterize_all(
                path,
                output_path,
                dpi,
                quality,
                progress_cb,
                should_cancel,
                cleanup_on_cancel,
            )

        if result_path is None or not result_path.exists():
            return CompressResult(
                path=output_path,
                original_size=orig_size,
                compressed_size=0,
                pages_preserved=preserved,
                pages_rasterized=rasterized,
            )

        if remove_meta:
            try:
                doc = fitz.open(str(result_path))
                doc.set_metadata({})
                doc.save(str(result_path), garbage=4, deflate=True, clean=True)
                doc.close()
            except Exception:
                pass

        new_size = result_path.stat().st_size
        ratio = (1 - new_size / orig_size) * 100 if orig_size > 0 else 0
        logger.info(
            f"压缩完成: {orig_size/1024:.0f}KB -> {new_size/1024:.0f}KB "
            f"(节省{ratio:.1f}%, 保留{preserved}页/栅格化{rasterized}页)"
        )
        return CompressResult(
            path=result_path,
            original_size=orig_size,
            compressed_size=new_size,
            pages_preserved=preserved,
            pages_rasterized=rasterized,
        )

    def _compress_rasterize_all(
        self,
        path: Path,
        output_path: Path,
        dpi: int,
        quality: int,
        progress_cb: Optional[Callable[[int, int], None]],
        should_cancel: Optional[Callable[[], bool]],
        cleanup_on_cancel: bool,
    ) -> tuple[Optional[Path], int, int]:
        src_doc = fitz.open(str(path))
        out_doc = fitz.open()
        total = len(src_doc)
        cancelled = False

        for i, page in enumerate(src_doc):
            if should_cancel and should_cancel():
                cancelled = True
                break
            self._rasterize_page(page, out_doc, dpi, quality)
            if progress_cb:
                progress_cb(i + 1, total)

        if cancelled and cleanup_on_cancel:
            src_doc.close()
            out_doc.close()
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None, 0, 0

        out_doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        src_doc.close()
        out_doc.close()
        return output_path, 0, total

    def _compress_smart(
        self,
        path: Path,
        output_path: Path,
        dpi: int,
        quality: int,
        text_threshold: int,
        progress_cb: Optional[Callable[[int, int], None]],
        should_cancel: Optional[Callable[[], bool]],
        cleanup_on_cancel: bool,
    ) -> tuple[Optional[Path], int, int]:
        src_doc = fitz.open(str(path))
        out_doc = fitz.open()
        total = len(src_doc)
        preserved = 0
        rasterized = 0
        cancelled = False

        for i, page in enumerate(src_doc):
            if should_cancel and should_cancel():
                cancelled = True
                break
            if len(page.get_text().strip()) >= text_threshold:
                out_doc.insert_pdf(src_doc, from_page=i, to_page=i)
                preserved += 1
            else:
                self._rasterize_page(page, out_doc, dpi, quality)
                rasterized += 1
            if progress_cb:
                progress_cb(i + 1, total)

        if cancelled and cleanup_on_cancel:
            src_doc.close()
            out_doc.close()
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None, preserved, rasterized

        out_doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        src_doc.close()
        out_doc.close()
        return output_path, preserved, rasterized

    @staticmethod
    def _rasterize_page(page: fitz.Page, out_doc: fitz.Document, dpi: int, quality: int) -> None:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=quality)
        img_rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
        new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(img_rect, stream=img_bytes)


# ─────────────────────────────────────────────
# PDF 加密引擎
# ─────────────────────────────────────────────

class PDFEncryptor:
    """PDF 加密与权限控制"""

    def encrypt(
        self,
        path: str | Path,
        output_path: str | Path,
        user_password: str,
        owner_password: str = "",
        allow_print: bool = True,
        allow_copy: bool = True,
        allow_edit: bool = True,
        allow_annotations: bool = True,
    ) -> Path:
        """
        加密 PDF

        Args:
            path: 源PDF
            output_path: 输出路径
            user_password: 用户密码（打开文档）
            owner_password: 所有者密码（修改权限）
            allow_print/copy/edit/annotations: 权限控制
        """
        from app.utils.deps import ensure_pdf_encrypt_ready

        ensure_pdf_encrypt_ready()

        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(path))
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # 构造权限标志
        permissions = 0
        if allow_print:
            permissions |= 0b000000000100  # bit 2
        if allow_copy:
            permissions |= 0b000000010000  # bit 4
        if allow_edit:
            permissions |= 0b000000001000  # bit 3
        if allow_annotations:
            permissions |= 0b000000100000  # bit 5

        writer.encrypt(
            user_password=user_password,
            owner_password=owner_password or user_password,
            permissions_flag=permissions,
            algorithm="AES-256",
        )

        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(f"加密完成: {output_path.name}")
        return output_path

    def decrypt(
        self,
        path: str | Path,
        output_path: str | Path,
        password: str,
    ) -> Path:
        """解密PDF（移除密码保护）"""
        from app.utils.deps import ensure_pdf_encrypt_ready

        ensure_pdf_encrypt_ready()

        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(path))
        if not reader.decrypt(password):
            raise ValueError("密码错误，无法解密")

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(f"解密完成: {output_path.name}")
        return output_path


# ─────────────────────────────────────────────
# PDF 水印引擎
# ─────────────────────────────────────────────

class PDFWatermarker:
    """PDF 水印添加引擎"""

    def add_text_watermark(
        self,
        path: str | Path,
        output_path: str | Path,
        options: WatermarkOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        """
        添加文字水印

        Args:
            path: 源PDF
            output_path: 输出路径
            options: 水印选项
        """
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total = len(doc)
        target_pages = options.pages if options.pages is not None else list(range(total))
        cancelled = False

        for i, page in enumerate(doc):
            if should_cancel and should_cancel():
                cancelled = True
                break
            if i in target_pages:
                rect = page.rect
                opacity = options.opacity
                rotation = int(options.rotation) % 360

                if options.position == "tile":
                    text_len = len(options.text) * options.font_size * 0.6
                    spacing_x = max(text_len * 1.5, options.font_size * 3)
                    spacing_y = max(options.font_size * 4, 60)
                    y = spacing_y * 0.3
                    while y < rect.height:
                        x = spacing_x * 0.2
                        while x < rect.width:
                            self._insert_text_watermark(
                                page, options, x, y, rotation, opacity
                            )
                            x += spacing_x
                        y += spacing_y
                else:
                    text_len = len(options.text) * options.font_size * 0.6
                    cx = rect.width / 2
                    cy = rect.height / 2
                    x = cx - text_len / 2
                    y = cy
                    self._insert_text_watermark(
                        page, options, x, y, rotation, opacity, origin=fitz.Point(cx, cy)
                    )

            if progress_cb:
                progress_cb(i + 1, total)

        if cancelled and cleanup_on_cancel:
            doc.close()
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            return output_path

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"水印添加完成: {output_path.name}")
        return output_path

    @staticmethod
    def _insert_text_watermark(
        page: fitz.Page,
        options: WatermarkOptions,
        x: float,
        y: float,
        rotation: int,
        opacity: float,
        origin: Optional[fitz.Point] = None,
    ) -> None:
        point = fitz.Point(x, y)
        if origin is None:
            origin = point
        if rotation in (0, 90, 180, 270):
            page.insert_text(
                point=point,
                text=options.text,
                fontsize=options.font_size,
                rotate=rotation,
                color=options.color,
                fill_opacity=opacity,
            )
        else:
            mat = fitz.Matrix(1, 1).prerotate(rotation)
            page.insert_text(
                point=point,
                text=options.text,
                fontsize=options.font_size,
                color=options.color,
                fill_opacity=opacity,
                morph=(origin, mat),
            )

    def add_image_watermark(
        self,
        path: str | Path,
        output_path: str | Path,
        options: WatermarkOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        """添加图片水印（居中或平铺）"""
        if not options.image_path or not Path(options.image_path).is_file():
            raise ValueError("请提供有效的水印图片路径")

        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img_path = str(options.image_path)

        doc = fitz.open(str(path))
        total = len(doc)
        target_pages = options.pages if options.pages is not None else list(range(total))
        cancelled = False

        with fitz.open(img_path) as img_doc:
            img_page = img_doc[0]
            img_rect_src = img_page.rect
            base_w = img_rect_src.width * options.image_scale
            base_h = img_rect_src.height * options.image_scale

        for i, page in enumerate(doc):
            if should_cancel and should_cancel():
                cancelled = True
                break
            if i not in target_pages:
                if progress_cb:
                    progress_cb(i + 1, total)
                continue

            rect = page.rect
            opacity = max(0.0, min(1.0, options.opacity))

            if options.position == "tile":
                spacing_x = base_w * 1.6
                spacing_y = base_h * 1.6
                y = base_h * 0.2
                while y < rect.height:
                    x = base_w * 0.2
                    while x < rect.width:
                        target = fitz.Rect(x, y, x + base_w, y + base_h)
                        self._insert_watermark_image(
                            page, img_path, target, opacity, options.rotation
                        )
                        x += spacing_x
                    y += spacing_y
            else:
                max_w = rect.width * 0.45
                max_h = rect.height * 0.45
                scale = min(max_w / base_w, max_h / base_h, 1.0)
                w = base_w * scale
                h = base_h * scale
                x0 = (rect.width - w) / 2
                y0 = (rect.height - h) / 2
                target = fitz.Rect(x0, y0, x0 + w, y0 + h)
                self._insert_watermark_image(
                    page, img_path, target, opacity, options.rotation
                )

            if progress_cb:
                progress_cb(i + 1, total)

        if cancelled and cleanup_on_cancel:
            doc.close()
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            return output_path

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"图片水印添加完成: {output_path.name}")
        return output_path

    @staticmethod
    def _insert_watermark_image(
        page: fitz.Page,
        img_path: str,
        rect: fitz.Rect,
        opacity: float,
        rotation: float,
    ) -> None:
        rotation = float(rotation) % 360
        stream = PDFWatermarker._load_watermark_stream(img_path, opacity, rotation)
        rotate_arg = int(rotation) if rotation in (0, 90, 180, 270) else 0
        page.insert_image(
            rect,
            stream=stream,
            overlay=True,
            rotate=rotate_arg,
        )

    @staticmethod
    def _load_watermark_stream(img_path: str, opacity: float, rotation: float = 0) -> bytes:
        opacity = max(0.0, min(1.0, opacity))
        rotation = float(rotation) % 360
        try:
            from PIL import Image
            import io
            img = Image.open(img_path).convert("RGBA")
            if rotation not in (0, 90, 180, 270):
                img = img.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
            if opacity < 0.999:
                alpha = img.getchannel("A")
                alpha = alpha.point(lambda p: int(p * opacity))
                img.putalpha(alpha)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            with open(img_path, "rb") as f:
                return f.read()


# ─────────────────────────────────────────────
# PDF 页码引擎
# ─────────────────────────────────────────────

class PDFPageNumberer:
    """PDF 页码添加引擎"""

    POSITION_MAP = {
        "bottom_center": lambda w, h, m: (w / 2, h - m),
        "bottom_right":  lambda w, h, m: (w - m, h - m),
        "bottom_left":   lambda w, h, m: (m, h - m),
        "top_center":    lambda w, h, m: (w / 2, m),
        "top_right":     lambda w, h, m: (w - m, m),
        "top_left":      lambda w, h, m: (m, m),
    }

    def add_page_numbers(
        self,
        path: str | Path,
        output_path: str | Path,
        options: PageNumberOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """
        添加页码

        Args:
            path: 源PDF
            output_path: 输出路径
            options: 页码选项
        """
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total = len(doc)
        pos_fn = self.POSITION_MAP.get(options.position, self.POSITION_MAP["bottom_center"])

        for i, page in enumerate(doc):
            page_num = options.start_number + i
            if options.skip_first and i == 0:
                continue
            if i < options.start_page - 1:
                continue

            rect = page.rect
            x, y = pos_fn(rect.width, rect.height, options.margin)
            text = options.format_str.format(n=page_num, total=total)

            page.insert_text(
                point=fitz.Point(x, y),
                text=text,
                fontsize=options.font_size,
                color=(0, 0, 0),
            )

            if progress_cb:
                progress_cb(i + 1, total)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"页码添加完成: {output_path.name}")
        return output_path


# ─────────────────────────────────────────────
# 页面操作工具
# ─────────────────────────────────────────────

class PDFPageEditor:
    """PDF 页面编辑工具（旋转/删除/裁剪）"""

    def rotate_pages(
        self,
        path: str | Path,
        output_path: str | Path,
        page_angles: dict[int, int],
    ) -> Path:
        """
        旋转指定页面

        Args:
            path: 源PDF
            output_path: 输出路径
            page_angles: {page_index: angle} angle 为 0/90/180/270
        """
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(path))
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            if i in page_angles:
                page.rotate(page_angles[i])
            writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(f"页面旋转完成: {output_path.name}")
        return output_path

    def delete_pages(
        self,
        path: str | Path,
        output_path: str | Path,
        page_indices: list[int],
    ) -> Path:
        """删除指定页面（0-based）"""
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(path))
        writer = PdfWriter()
        to_delete = set(page_indices)

        for i, page in enumerate(reader.pages):
            if i not in to_delete:
                writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info(f"删除 {len(to_delete)} 页 -> {output_path.name}")
        return output_path

    def insert_blank_pages(
        self,
        path: str | Path,
        output_path: str | Path,
        after_page_index: int,
        count: int = 1,
    ) -> Path:
        """在指定页之后插入空白页（after_page_index=-1 表示文档开头）"""
        if count < 1:
            raise ValueError("插入页数至少为 1")

        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        if not len(doc):
            raise ValueError("PDF 无页面")

        if after_page_index < 0:
            ref = doc[0]
            insert_at = 0
        else:
            after_page_index = min(after_page_index, len(doc) - 1)
            ref = doc[after_page_index]
            insert_at = after_page_index + 1

        width, height = ref.rect.width, ref.rect.height
        for _ in range(count):
            doc.new_page(pno=insert_at, width=width, height=height)
            insert_at += 1

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"已插入 {count} 页空白页 -> {output_path.name}")
        return output_path

    def duplicate_pages(
        self,
        path: str | Path,
        output_path: str | Path,
        page_indices: list[int],
    ) -> Path:
        """复制指定页并紧挨插入其后"""
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        valid = sorted({i for i in page_indices if 0 <= i < len(doc)}, reverse=True)
        if not valid:
            doc.close()
            raise ValueError("没有有效的页面可复制")

        for idx in valid:
            doc.fullcopy_page(idx, idx + 1)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()
        logger.info(f"已复制 {len(valid)} 页 -> {output_path.name}")
        return output_path

    def crop_page(
        self,
        path: str | Path,
        output_path: str | Path,
        page_index: int,
        crop_rect: tuple[float, float, float, float],
    ) -> Path:
        """
        裁剪指定页面

        Args:
            crop_rect: (x0, y0, x1, y1) PDF坐标系（pt）
        """
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        page = doc[page_index]
        page.set_cropbox(fitz.Rect(*crop_rect))
        doc.save(str(output_path))
        doc.close()

        logger.info(f"页面裁剪完成: {output_path.name}")
        return output_path
