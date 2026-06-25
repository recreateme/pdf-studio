"""
PDF Studio - 多图合并（长图 / 网格拼图）
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from app.utils.helpers import get_unique_path
from app.utils.logger import logger


@dataclass
class ImageMergeOptions:
    """图片合并选项"""
    output_dir: Path
    output_stem: str = "合并"
    mode: str = "vertical"           # vertical / horizontal / grid
    format: str = "PNG"              # PNG / JPEG / WEBP
    jpeg_quality: int = 90
    margin: int = 0                  # px 外边距
    spacing: int = 0                 # px 图间距
    background: tuple[int, int, int] = (255, 255, 255)
    grid_rows: int = 3
    grid_cols: int = 3
    align_center: bool = True        # 长图拼接时窄图居中
    fixed_canvas_width: int = 0      # 纵向长图固定宽度，0=以最宽图为准
    fixed_canvas_height: int = 0     # 横向长图固定高度，0=以最高图为准
    page_suffix_template: str = "_{page:03d}"  # 网格多页时页码后缀，{page} 从 1 起
    webp_lossless: bool = False


class ImageMerger:
    """多图合并引擎"""

    MAX_IMAGE_PIXELS = 50_000_000
    MAX_IMAGE_SIDE = 8000
    PREVIEW_MAX_IMAGES = 24
    PREVIEW_MAX_SIDE = 520

    def merge(
        self,
        image_paths: list[str | Path],
        options: ImageMergeOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> list[Path]:
        paths = [Path(p) for p in image_paths if Path(p).is_file()]
        if not paths:
            raise ValueError("没有可合并的图片")

        options.output_dir.mkdir(parents=True, exist_ok=True)
        mode = options.mode
        if mode == "vertical":
            canvas = self._compose_vertical(paths, options, progress_cb, should_cancel)
            return [self._save_canvas(canvas, options, page_index=0, page_count=1)]
        if mode == "horizontal":
            canvas = self._compose_horizontal(paths, options, progress_cb, should_cancel)
            return [self._save_canvas(canvas, options, page_index=0, page_count=1)]
        if mode == "grid":
            return self._merge_grid(paths, options, progress_cb, should_cancel)
        raise ValueError(f"不支持的合并模式: {mode}")

    def render_preview(
        self,
        image_paths: list[str | Path],
        options: ImageMergeOptions,
        *,
        max_images: int | None = None,
        max_side: int | None = None,
    ) -> Image.Image:
        """生成低分辨率预览图（不落盘）。"""
        limit = max_images if max_images is not None else self.PREVIEW_MAX_IMAGES
        side = max_side if max_side is not None else self.PREVIEW_MAX_SIDE
        paths = [Path(p) for p in image_paths if Path(p).is_file()][:limit]
        if not paths:
            raise ValueError("没有可预览的图片")

        if options.mode == "vertical":
            canvas = self._compose_vertical(paths, options, None, None, preview_side=side)
        elif options.mode == "horizontal":
            canvas = self._compose_horizontal(paths, options, None, None, preview_side=side)
        elif options.mode == "grid":
            canvas = self._compose_grid_page(
                self._load_all(paths, None, None, preview_side=side),
                options,
                page_index=0,
            )
        else:
            raise ValueError(f"不支持的合并模式: {options.mode}")

        return self._scale_to_max_side(canvas, side)

    def _load_image(self, path: Path, *, preview_side: int = 0) -> Image.Image:
        with Image.open(path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)
            if img.mode not in ("RGB", "RGBA", "L"):
                img = img.convert("RGBA")
            elif img.mode == "L":
                img = img.convert("RGB")
            loaded = self._limit_image_size(img.copy())
            if preview_side > 0:
                loaded = self._scale_to_max_side(loaded, preview_side)
            return loaded

    def _limit_image_size(self, img: Image.Image) -> Image.Image:
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

    @staticmethod
    def _scale_to_max_side(img: Image.Image, max_side: int) -> Image.Image:
        if max_side <= 0:
            return img
        w, h = img.size
        if max(w, h) <= max_side:
            return img
        scale = max_side / max(w, h)
        return img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )

    @staticmethod
    def _scale_to_width(img: Image.Image, target_w: int) -> Image.Image:
        if target_w <= 0 or img.width == target_w:
            return img
        scale = target_w / img.width
        new_h = max(1, int(img.height * scale))
        return img.resize((target_w, new_h), Image.Resampling.LANCZOS)

    @staticmethod
    def _scale_to_height(img: Image.Image, target_h: int) -> Image.Image:
        if target_h <= 0 or img.height == target_h:
            return img
        scale = target_h / img.height
        new_w = max(1, int(img.width * scale))
        return img.resize((new_w, target_h), Image.Resampling.LANCZOS)

    def _compose_vertical(
        self,
        paths: list[Path],
        options: ImageMergeOptions,
        progress_cb,
        should_cancel,
        *,
        preview_side: int = 0,
    ) -> Image.Image:
        images = self._load_all(paths, progress_cb, should_cancel, preview_side=preview_side)
        margin = options.margin
        spacing = options.spacing
        bg = options.background

        if options.fixed_canvas_width > 0:
            canvas_w = options.fixed_canvas_width
            images = [self._scale_to_width(img, canvas_w) for img in images]
        else:
            canvas_w = max(img.width for img in images)

        total_h = margin * 2 + sum(img.height for img in images) + spacing * max(0, len(images) - 1)
        canvas = Image.new("RGB", (canvas_w + margin * 2, total_h), bg)

        y = margin
        for img in images:
            if options.align_center:
                x = margin + (canvas_w - img.width) // 2
            else:
                x = margin
            self._paste_rgba(canvas, img, x, y)
            y += img.height + spacing
        return canvas

    def _compose_horizontal(
        self,
        paths: list[Path],
        options: ImageMergeOptions,
        progress_cb,
        should_cancel,
        *,
        preview_side: int = 0,
    ) -> Image.Image:
        images = self._load_all(paths, progress_cb, should_cancel, preview_side=preview_side)
        margin = options.margin
        spacing = options.spacing
        bg = options.background

        if options.fixed_canvas_height > 0:
            canvas_h = options.fixed_canvas_height
            images = [self._scale_to_height(img, canvas_h) for img in images]
        else:
            canvas_h = max(img.height for img in images)

        total_w = margin * 2 + sum(img.width for img in images) + spacing * max(0, len(images) - 1)
        canvas = Image.new("RGB", (total_w, canvas_h + margin * 2), bg)

        x = margin
        for img in images:
            if options.align_center:
                y = margin + (canvas_h - img.height) // 2
            else:
                y = margin
            self._paste_rgba(canvas, img, x, y)
            x += img.width + spacing
        return canvas

    def _compose_grid_page(
        self,
        chunk: list[Image.Image],
        options: ImageMergeOptions,
        *,
        page_index: int = 0,
    ) -> Image.Image:
        rows, cols = max(1, options.grid_rows), max(1, options.grid_cols)
        margin = options.margin
        spacing = options.spacing
        bg = options.background

        cell_w = max((img.width for img in chunk), default=1)
        cell_h = max((img.height for img in chunk), default=1)
        canvas_w = margin * 2 + cols * cell_w + spacing * max(0, cols - 1)
        canvas_h = margin * 2 + rows * cell_h + spacing * max(0, rows - 1)
        canvas = Image.new("RGB", (canvas_w, canvas_h), bg)

        for cell_idx, img in enumerate(chunk):
            row, col = divmod(cell_idx, cols)
            cell_x = margin + col * (cell_w + spacing)
            cell_y = margin + row * (cell_h + spacing)
            fitted = self._fit_in_cell(img, cell_w, cell_h)
            paste_x = cell_x + (cell_w - fitted.width) // 2
            paste_y = cell_y + (cell_h - fitted.height) // 2
            self._paste_rgba(canvas, fitted, paste_x, paste_y)
        return canvas

    def _merge_grid(
        self,
        paths: list[Path],
        options: ImageMergeOptions,
        progress_cb,
        should_cancel,
    ) -> list[Path]:
        rows, cols = max(1, options.grid_rows), max(1, options.grid_cols)
        per_page = rows * cols

        all_images = self._load_all(paths, progress_cb, should_cancel)
        total_pages = (len(all_images) + per_page - 1) // per_page
        outputs: list[Path] = []

        for page_idx in range(total_pages):
            if should_cancel and should_cancel():
                break
            chunk = all_images[page_idx * per_page: (page_idx + 1) * per_page]
            canvas = self._compose_grid_page(chunk, options, page_index=page_idx)
            outputs.append(
                self._save_canvas(canvas, options, page_index=page_idx, page_count=total_pages)
            )

        logger.info(f"图片网格合并完成: {len(outputs)} 张")
        return outputs

    def _load_all(
        self,
        paths: list[Path],
        progress_cb,
        should_cancel,
        *,
        preview_side: int = 0,
    ) -> list[Image.Image]:
        images: list[Image.Image] = []
        total = len(paths)
        for idx, path in enumerate(paths):
            if should_cancel and should_cancel():
                raise RuntimeError("任务已取消")
            try:
                images.append(self._load_image(path, preview_side=preview_side))
            except Exception as exc:
                logger.error(f"加载图片失败 {path.name}: {exc}")
                raise RuntimeError(f"无法加载图片: {path.name}") from exc
            if progress_cb:
                progress_cb(idx + 1, total)
        return images

    @staticmethod
    def _fit_in_cell(img: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
        scale = min(cell_w / img.width, cell_h / img.height, 1.0)
        if scale >= 1.0:
            return img
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    @staticmethod
    def _paste_rgba(canvas: Image.Image, img: Image.Image, x: int, y: int) -> None:
        if img.mode == "RGBA":
            canvas.paste(img, (x, y), img.split()[3])
        else:
            canvas.paste(img, (x, y))

    def _format_page_suffix(
        self,
        options: ImageMergeOptions,
        page_index: int,
        page_count: int,
    ) -> str:
        if page_count <= 1:
            return ""
        template = options.page_suffix_template.strip() or "_{page:03d}"
        page_num = page_index + 1
        if "{page" in template:
            return template.format(page=page_num, index=page_index, total=page_count)
        return f"{template}{page_num:03d}"

    def _save_canvas(
        self,
        canvas: Image.Image,
        options: ImageMergeOptions,
        *,
        page_index: int = 0,
        page_count: int = 1,
    ) -> Path:
        fmt = options.format.upper()
        ext = {
            "JPEG": ".jpg",
            "JPG": ".jpg",
            "PNG": ".png",
            "WEBP": ".webp",
        }.get(fmt, ".png")

        suffix = self._format_page_suffix(options, page_index, page_count)
        out_path = options.output_dir / f"{options.output_stem}{suffix}{ext}"
        out_path = get_unique_path(out_path)

        save_img = canvas
        if fmt in ("JPEG", "JPG") and save_img.mode != "RGB":
            save_img = save_img.convert("RGB")

        save_kwargs: dict = {}
        if fmt in ("JPEG", "JPG"):
            save_kwargs["quality"] = options.jpeg_quality
            save_kwargs["optimize"] = True
            fmt = "JPEG"
        elif fmt == "WEBP":
            save_kwargs["quality"] = options.jpeg_quality
            if options.webp_lossless:
                save_kwargs["lossless"] = True

        save_img.save(str(out_path), format=fmt, **save_kwargs)
        logger.info(f"图片合并完成 -> {out_path.name}")
        return out_path
