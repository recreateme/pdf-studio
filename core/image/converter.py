"""
PDF Studio - 图像处理引擎
提供 PDF↔图片转换、图像增强等功能
依赖：PyMuPDF + Pillow + OpenCV
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import fitz
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

from app.utils.logger import logger
from app.utils.helpers import get_unique_path, make_temp_dir
from app.config.constants import (
    SUPPORTED_IMAGE_EXTENSIONS, IMAGE_EXPORT_FORMATS
)


# ─────────────────────────────────────────────
# 数据类型
# ─────────────────────────────────────────────

@dataclass
class PDFToImageOptions:
    """PDF转图片选项"""
    output_dir: Path
    format: str = "PNG"             # PNG/JPEG/WEBP/TIFF/BMP
    dpi: int = 150
    jpeg_quality: int = 85          # 仅JPEG有效
    pages: Optional[list[int]] = None   # None=全部页
    name_template: str = "{stem}_p{page:04d}"
    # 图像增强
    sharpen: bool = False
    denoise: bool = False
    grayscale: bool = False
    binarize: bool = False
    binarize_threshold: int = 128


@dataclass
class ImageToPDFOptions:
    """图片转PDF选项"""
    output_path: Path
    layout: str = "single"          # single/multi/grid9
    page_size: str = "A4"           # A4/A3/Letter/原始尺寸
    margin: float = 20.0            # pt
    auto_resize: bool = True        # 自动填满页面
    auto_rotate: bool = True        # 自动旋转适配
    add_watermark: bool = False
    watermark_text: str = ""
    add_page_numbers: bool = False
    compress_images: bool = True
    jpeg_quality: int = 85


@dataclass
class ImageEnhanceOptions:
    """图像增强选项"""
    sharpen: float = 1.0            # 1.0=不变，>1增强
    contrast: float = 1.0
    brightness: float = 1.0
    denoise: bool = False
    grayscale: bool = False
    binarize: bool = False
    binarize_threshold: int = 128
    deskew: bool = False            # 自动纠偏
    remove_border: bool = False     # 去黑边


# ─────────────────────────────────────────────
# PDF → 图片
# ─────────────────────────────────────────────

class PDFToImageConverter:
    """PDF 转图片转换器"""

    PAGE_SIZES = {
        "A4": (595, 842),
        "A3": (842, 1190),
        "Letter": (612, 792),
    }

    def convert(
        self,
        path: str | Path,
        options: PDFToImageOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> list[Path]:
        """
        将PDF页面转换为图片

        Args:
            path: 源PDF路径
            options: 转换选项
            progress_cb: 进度回调 (current, total)

        Returns:
            生成的图片路径列表
        """
        path = Path(path)
        options.output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total_pages = len(doc)
        target_pages = options.pages if options.pages is not None else list(range(total_pages))
        outputs = []
        cancelled = False

        fmt = options.format.upper()
        ext = {
            "JPEG": ".jpg", "JPG": ".jpg",
            "PNG": ".png", "WEBP": ".webp",
            "TIFF": ".tiff", "BMP": ".bmp",
        }.get(fmt, f".{fmt.lower()}")

        for idx, page_idx in enumerate(target_pages):
            if should_cancel and should_cancel():
                cancelled = True
                break
            if page_idx >= total_pages:
                continue

            page = doc[page_idx]
            mat = fitz.Matrix(options.dpi / 72, options.dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # 转为 PIL Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            # 图像增强
            img = self._enhance(img, options)

            # 命名
            name = options.name_template.format(
                stem=path.stem,
                page=page_idx + 1,
                index=idx + 1,
            )
            out_path = options.output_dir / f"{name}{ext}"
            out_path = get_unique_path(out_path)

            # 保存
            save_kwargs = {}
            if fmt in ("JPEG", "JPG"):
                save_kwargs["quality"] = options.jpeg_quality
                save_kwargs["optimize"] = True
            elif fmt == "WEBP":
                save_kwargs["quality"] = options.jpeg_quality

            img.save(str(out_path), **save_kwargs)
            outputs.append(out_path)
            logger.debug(f"转换第 {page_idx + 1} 页 -> {out_path.name}")

            if progress_cb:
                progress_cb(idx + 1, len(target_pages))

        doc.close()
        if cancelled and cleanup_on_cancel:
            for p in outputs:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            return []
        logger.info(f"PDF转图片完成: 共 {len(outputs)} 张")
        return outputs

    def pdf_to_long_image(
        self,
        path: str | Path,
        output_path: str | Path,
        options: PDFToImageOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """将 PDF 页面纵向拼接为一张长图"""
        path = Path(path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(path))
        total_pages = len(doc)
        target_pages = options.pages if options.pages is not None else list(range(total_pages))
        images: list[Image.Image] = []

        for idx, page_idx in enumerate(target_pages):
            if should_cancel and should_cancel():
                doc.close()
                raise RuntimeError("任务已取消")
            if page_idx >= total_pages:
                continue

            page = doc[page_idx]
            mat = fitz.Matrix(options.dpi / 72, options.dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(self._enhance(img, options))
            if progress_cb:
                progress_cb(idx + 1, len(target_pages))

        doc.close()
        if not images:
            raise ValueError("没有可转换的页面")

        max_w = max(img.width for img in images)
        total_h = sum(img.height for img in images)
        canvas = Image.new("RGB", (max_w, total_h), (255, 255, 255))
        y = 0
        for img in images:
            x = (max_w - img.width) // 2
            canvas.paste(img, (x, y))
            y += img.height

        fmt = options.format.upper()
        save_kwargs: dict = {}
        if fmt in ("JPEG", "JPG"):
            save_kwargs["quality"] = options.jpeg_quality
            fmt = "JPEG"
        canvas.save(str(output_path), format=fmt, **save_kwargs)
        logger.info(f"PDF 长图导出完成 -> {output_path.name}")
        return output_path

    def _enhance(self, img: Image.Image, options: PDFToImageOptions) -> Image.Image:
        """应用图像增强"""
        if options.grayscale or options.binarize:
            img = img.convert("L")

        if options.binarize:
            img = img.point(lambda p: 255 if p > options.binarize_threshold else 0)
            img = img.convert("1")
            return img

        if options.sharpen:
            img = img.filter(ImageFilter.SHARPEN)

        if options.denoise:
            arr = np.array(img)
            arr = cv2.fastNlMeansDenoisingColored(arr, None, 10, 10, 7, 21) \
                if arr.ndim == 3 else cv2.fastNlMeansDenoising(arr)
            img = Image.fromarray(arr)

        return img


# ─────────────────────────────────────────────
# 图片 → PDF
# ─────────────────────────────────────────────

class ImageToPDFConverter:
    """图片转PDF转换器"""

    # 超大图自动缩小，避免内存溢出（如 18MB+ 扫描图）
    MAX_IMAGE_PIXELS = 50_000_000   # 约 7000×7000
    MAX_IMAGE_SIDE = 8000

    PAGE_SIZE_MAP = {
        "A4": (595.28, 841.89),
        "A3": (841.89, 1190.55),
        "Letter": (612.0, 792.0),
        "Legal": (612.0, 1008.0),
    }

    def convert(
        self,
        image_paths: list[str | Path],
        options: ImageToPDFOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        """
        将多张图片合并为PDF

        Args:
            image_paths: 图片路径列表（顺序即页面顺序）
            options: 转换选项
            progress_cb: 进度回调

        Returns:
            生成的PDF路径
        """
        image_paths = [Path(p) for p in image_paths]
        output_path = Path(options.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 允许打开超大本地图（随后由 _limit_image_size 缩小）
        old_max_pixels = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = self.MAX_IMAGE_PIXELS
        try:
            doc = fitz.open()
            if options.layout == "single":
                self._layout_single(doc, image_paths, options, progress_cb, should_cancel)
            elif options.layout == "grid9":
                self._layout_grid(
                    doc, image_paths, options, progress_cb, should_cancel, cols=3, rows=3
                )
            else:
                self._layout_single(doc, image_paths, options, progress_cb, should_cancel)

            if should_cancel and should_cancel() and cleanup_on_cancel:
                doc.close()
                return output_path

            doc.save(str(output_path), garbage=4, deflate=True)
            doc.close()
        finally:
            Image.MAX_IMAGE_PIXELS = old_max_pixels

        logger.info(f"图片转PDF完成 -> {output_path.name}")
        return output_path

    def _layout_single(
        self,
        doc: fitz.Document,
        paths: list[Path],
        options: ImageToPDFOptions,
        progress_cb,
        should_cancel=None,
    ) -> None:
        """单图单页布局"""
        total = len(paths)
        page_w, page_h = self._get_page_size(options.page_size)
        margin = options.margin

        for idx, img_path in enumerate(paths):
            if should_cancel and should_cancel():
                break
            try:
                with Image.open(str(img_path)) as img:
                    img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
                    img = self._limit_image_size(img)
                    img_w, img_h = img.size

                    if options.page_size == "原始尺寸":
                        # 按图片原始尺寸创建页面（96dpi 屏幕基准 → 72dpi PDF 点）
                        pw = img_w * 72 / 96
                        ph = img_h * 72 / 96
                    else:
                        pw, ph = page_w, page_h

                    # 自动旋转：横图用横向页面
                    if options.auto_rotate and img_w > img_h and pw < ph:
                        pw, ph = ph, pw

                    page = doc.new_page(width=pw, height=ph)

                    # 计算图像放置区域（统一使用 PDF 点单位）
                    avail_w = pw - 2 * margin
                    avail_h = ph - 2 * margin
                    img_w_pt = img_w * 72 / 96
                    img_h_pt = img_h * 72 / 96

                    if options.auto_resize:
                        scale = min(avail_w / img_w_pt, avail_h / img_h_pt, 1.0)
                        draw_w = img_w_pt * scale
                        draw_h = img_h_pt * scale
                    else:
                        draw_w, draw_h = img_w_pt, img_h_pt

                    x = margin + (avail_w - draw_w) / 2
                    y = margin + (avail_h - draw_h) / 2
                    rect = fitz.Rect(x, y, x + draw_w, y + draw_h)

                    # 插入图像（JPEG 流可减小 PDF 体积）
                    if options.compress_images:
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=options.jpeg_quality, optimize=True)
                        page.insert_image(rect, stream=buf.getvalue())
                    else:
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        page.insert_image(rect, stream=buf.getvalue())

            except Exception as e:
                logger.error(f"处理图片失败 {img_path.name}: {e}")

            if progress_cb:
                progress_cb(idx + 1, total)

    def _layout_grid(
        self,
        doc: fitz.Document,
        paths: list[Path],
        options: ImageToPDFOptions,
        progress_cb,
        should_cancel=None,
        cols: int = 3,
        rows: int = 3,
    ) -> None:
        """多图网格布局"""
        page_w, page_h = self._get_page_size(options.page_size)
        margin = options.margin
        per_page = cols * rows
        total = len(paths)

        for page_idx in range(0, total, per_page):
            if should_cancel and should_cancel():
                break
            chunk = paths[page_idx: page_idx + per_page]
            page = doc.new_page(width=page_w, height=page_h)

            cell_w = (page_w - 2 * margin - (cols - 1) * margin) / cols
            cell_h = (page_h - 2 * margin - (rows - 1) * margin) / rows

            for cell_idx, img_path in enumerate(chunk):
                col = cell_idx % cols
                row = cell_idx // cols
                x = margin + col * (cell_w + margin)
                y = margin + row * (cell_h + margin)
                rect = fitz.Rect(x, y, x + cell_w, y + cell_h)

                try:
                    img_data = open(str(img_path), "rb").read()
                    page.insert_image(rect, stream=img_data, keep_proportion=True)
                except Exception as e:
                    logger.error(f"网格图片插入失败 {img_path.name}: {e}")

            if progress_cb:
                progress_cb(min(page_idx + per_page, total), total)

    def _get_page_size(self, size: str) -> tuple[float, float]:
        return self.PAGE_SIZE_MAP.get(size, (595.28, 841.89))

    def _limit_image_size(self, img: Image.Image) -> Image.Image:
        """超大图等比缩小，避免 fitz/PIL 内存溢出"""
        w, h = img.size
        pixels = w * h
        if pixels <= self.MAX_IMAGE_PIXELS and max(w, h) <= self.MAX_IMAGE_SIDE:
            return img
        scale = min(
            (self.MAX_IMAGE_PIXELS / pixels) ** 0.5,
            self.MAX_IMAGE_SIDE / max(w, h),
        )
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        logger.warning(f"图片过大 ({w}×{h})，已缩小至 {new_w}×{new_h}")
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


# ─────────────────────────────────────────────
# 图像增强工具
# ─────────────────────────────────────────────

class ImageEnhancer:
    """图像增强处理器"""

    def enhance_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
        options: ImageEnhanceOptions,
    ) -> Path:
        """对单张图片应用增强并保存"""
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(input_path)
        if img.mode not in ("RGB", "L", "RGBA"):
            img = img.convert("RGB")
        result = self.enhance(img, options)
        save_kwargs: dict = {}
        ext = output_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            save_kwargs["quality"] = 92
            if result.mode == "RGBA":
                result = result.convert("RGB")
        result.save(output_path, **save_kwargs)
        return output_path

    def enhance_batch(
        self,
        input_paths: list[str | Path],
        output_dir: str | Path,
        options: ImageEnhanceOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[Path]:
        """批量增强扫描件/图片"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        total = len(input_paths)
        for idx, src in enumerate(input_paths):
            src = Path(src)
            out = output_dir / f"{src.stem}_enhanced{src.suffix or '.png'}"
            outputs.append(self.enhance_file(src, out, options))
            if progress_cb:
                progress_cb(idx + 1, total)
        return outputs

    def enhance(
        self,
        img: Image.Image,
        options: ImageEnhanceOptions,
    ) -> Image.Image:
        """
        对图像应用增强处理

        Args:
            img: PIL Image 对象
            options: 增强选项

        Returns:
            处理后的 PIL Image
        """
        # 去噪
        if options.denoise:
            arr = np.array(img)
            if arr.ndim == 3:
                arr = cv2.fastNlMeansDenoisingColored(arr, None, 10, 10, 7, 21)
            else:
                arr = cv2.fastNlMeansDenoising(arr)
            img = Image.fromarray(arr)

        # 灰度化
        if options.grayscale or options.binarize:
            img = img.convert("L")

        # 锐化
        if options.sharpen != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(options.sharpen)

        # 对比度
        if options.contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(options.contrast)

        # 亮度
        if options.brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(options.brightness)

        # 二值化
        if options.binarize:
            img = img.point(lambda p: 255 if p > options.binarize_threshold else 0)

        # 自动纠偏
        if options.deskew:
            img = self._deskew(img)

        # 去黑边
        if options.remove_border:
            img = self._remove_border(img)

        return img

    def _deskew(self, img: Image.Image) -> Image.Image:
        """
        自动纠偏（基于Hough变换）
        [接口已定义，完整实现使用 cv2.HoughLines]
        """
        arr = np.array(img.convert("L"))
        edges = cv2.Canny(arr, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)

        if lines is None:
            return img

        angles = []
        for line in lines[:20]:
            rho, theta = line[0]
            angle = np.degrees(theta) - 90
            if abs(angle) < 45:
                angles.append(angle)

        if not angles:
            return img

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.5:
            return img

        return img.rotate(-median_angle, expand=True, fillcolor=255)

    def _remove_border(self, img: Image.Image) -> Image.Image:
        """
        去黑边（自动裁剪边框）
        [接口已定义，基于轮廓检测]
        """
        arr = np.array(img.convert("L"))
        _, thresh = cv2.threshold(arr, 30, 255, cv2.THRESH_BINARY)
        coords = cv2.findNonZero(thresh)
        if coords is None:
            return img
        x, y, w, h = cv2.boundingRect(coords)
        return img.crop((x, y, x + w, y + h))
