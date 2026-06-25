"""
PDF Studio - 图片压缩（目标大小 / 按比例 / 指定质量）
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from app.utils.helpers import get_unique_path
from app.utils.logger import logger


@dataclass
class ImageCompressOptions:
    """图片压缩选项"""
    output_dir: Path
    mode: str = "target_size"          # target_size / scale / quality
    target_max_bytes: int = 512_000    # 目标大小上限（字节）
    scale_percent: int = 80            # 按比例缩放 1–100
    jpeg_quality: int = 85             # 指定质量模式
    output_format: str = "auto"        # auto / JPEG / WEBP / PNG
    output_suffix: str = "_compressed"
    webp_lossless: bool = False


@dataclass
class ImageCompressResult:
    """单张压缩结果"""
    input_path: Path
    output_path: Path
    original_size: int
    compressed_size: int
    quality_used: Optional[int] = None
    scale_used: Optional[float] = None

    @property
    def ratio_percent(self) -> float:
        if self.original_size <= 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100


class ImageCompressor:
    """图片压缩引擎"""

    MIN_QUALITY = 5
    MAX_QUALITY = 95
    MIN_SCALE = 0.05
    SCALE_STEP = 0.88

    def compress_batch(
        self,
        input_paths: list[str | Path],
        options: ImageCompressOptions,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> list[ImageCompressResult]:
        options.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[ImageCompressResult] = []
        total = len(input_paths)
        for idx, src in enumerate(input_paths):
            if should_cancel and should_cancel():
                raise RuntimeError("任务已取消")
            src_path = Path(src)
            if not src_path.is_file():
                continue
            try:
                results.append(self.compress_file(src_path, options))
            except Exception as exc:
                logger.error(f"压缩失败 {src_path.name}: {exc}")
                raise RuntimeError(f"压缩失败: {src_path.name} ({exc})") from exc
            if progress_cb:
                progress_cb(idx + 1, total)
        return results

    def compress_file(
        self,
        input_path: str | Path,
        options: ImageCompressOptions,
    ) -> ImageCompressResult:
        input_path = Path(input_path)
        original_size = input_path.stat().st_size

        with Image.open(input_path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)
            working = self._prepare_image(img)

            fmt = self._resolve_format(working, input_path, options)
            quality_used: Optional[int] = None
            scale_used: Optional[float] = None

            if options.mode == "target_size":
                if fmt == "PNG" and not options.webp_lossless:
                    fmt = "JPEG"
                    working = self._to_rgb(working)
                data, quality_used, scale_used = self._compress_to_target(
                    working, options.target_max_bytes, fmt, options,
                )
            elif options.mode == "scale":
                scale = max(1, min(100, options.scale_percent)) / 100.0
                scale_used = scale
                if scale < 1.0:
                    w, h = working.size
                    working = working.resize(
                        (max(1, int(w * scale)), max(1, int(h * scale))),
                        Image.Resampling.LANCZOS,
                    )
                quality_used = options.jpeg_quality
                data = self._encode(working, fmt, quality_used, options)
            else:
                quality_used = options.jpeg_quality
                data = self._encode(working, fmt, quality_used, options)

        out_path = self._output_path(input_path, options, fmt)
        out_path.write_bytes(data)
        logger.info(
            f"图片压缩 {input_path.name} -> {out_path.name} "
            f"({original_size} -> {len(data)} B)"
        )
        return ImageCompressResult(
            input_path=input_path,
            output_path=out_path,
            original_size=original_size,
            compressed_size=len(data),
            quality_used=quality_used,
            scale_used=scale_used,
        )

    def _prepare_image(self, img: Image.Image) -> Image.Image:
        if img.mode not in ("RGB", "RGBA", "L"):
            return img.convert("RGBA")
        return img.copy()

    @staticmethod
    def _to_rgb(img: Image.Image) -> Image.Image:
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        if img.mode != "RGB":
            return img.convert("RGB")
        return img

    def _resolve_format(
        self,
        img: Image.Image,
        input_path: Path,
        options: ImageCompressOptions,
    ) -> str:
        fmt = options.output_format.upper()
        if fmt != "AUTO":
            return {"JPG": "JPEG"}.get(fmt, fmt)

        ext = input_path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            return "JPEG"
        if ext == ".webp":
            return "WEBP"
        if ext == ".png":
            return "PNG" if options.mode != "target_size" else "JPEG"
        if ext in (".bmp", ".tif", ".tiff", ".gif"):
            return "JPEG"
        return "JPEG"

    def _output_path(
        self,
        input_path: Path,
        options: ImageCompressOptions,
        fmt: str,
    ) -> Path:
        ext_map = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}
        suffix = ext_map.get(fmt, input_path.suffix or ".jpg")
        stem = input_path.stem
        if options.output_suffix and not stem.endswith(options.output_suffix):
            stem = f"{stem}{options.output_suffix}"
        out = options.output_dir / f"{stem}{suffix}"
        return get_unique_path(out)

    def _encode(
        self,
        img: Image.Image,
        fmt: str,
        quality: int,
        options: ImageCompressOptions,
    ) -> bytes:
        save_img = img
        if fmt in ("JPEG", "WEBP") and save_img.mode == "RGBA":
            save_img = self._to_rgb(save_img)
        elif fmt == "JPEG" and save_img.mode != "RGB":
            save_img = save_img.convert("RGB")

        kwargs: dict = {}
        if fmt == "JPEG":
            kwargs["quality"] = max(1, min(100, quality))
            kwargs["optimize"] = True
        elif fmt == "WEBP":
            kwargs["quality"] = max(1, min(100, quality))
            if options.webp_lossless:
                kwargs["lossless"] = True
        elif fmt == "PNG":
            kwargs["optimize"] = True

        buf = io.BytesIO()
        save_img.save(buf, format=fmt, **kwargs)
        return buf.getvalue()

    def _compress_to_target(
        self,
        img: Image.Image,
        target_bytes: int,
        fmt: str,
        options: ImageCompressOptions,
    ) -> tuple[bytes, int, float]:
        if target_bytes <= 0:
            raise ValueError("目标大小必须大于 0")

        best_data: bytes | None = None
        best_quality = self.MIN_QUALITY
        best_scale = 1.0

        scale = 1.0
        while scale >= self.MIN_SCALE:
            if scale < 1.0:
                w, h = img.size
                working = img.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            else:
                working = img

            data, quality = self._best_quality_under_target(
                working, target_bytes, fmt, options,
            )
            if data is not None:
                best_data = data
                best_quality = quality
                best_scale = scale
                break
            scale *= self.SCALE_STEP

        if best_data is None:
            working = img.resize((1, 1), Image.Resampling.LANCZOS)
            best_data = self._encode(working, fmt, self.MIN_QUALITY, options)
            if len(best_data) > target_bytes:
                raise ValueError(
                    f"无法在 {target_bytes} 字节内压缩（最小输出 {len(best_data)} 字节）"
                )
            best_quality = self.MIN_QUALITY
            best_scale = self.MIN_SCALE

        return best_data, best_quality, best_scale

    def _best_quality_under_target(
        self,
        img: Image.Image,
        target_bytes: int,
        fmt: str,
        options: ImageCompressOptions,
    ) -> tuple[bytes | None, int]:
        if options.webp_lossless and fmt == "WEBP":
            data = self._encode(img, fmt, 100, options)
            return (data, 100) if len(data) <= target_bytes else (None, 100)

        lo, hi = self.MIN_QUALITY, self.MAX_QUALITY
        best_data: bytes | None = None
        best_q = self.MIN_QUALITY

        while lo <= hi:
            mid = (lo + hi) // 2
            data = self._encode(img, fmt, mid, options)
            if len(data) <= target_bytes:
                best_data = data
                best_q = mid
                lo = mid + 1
            else:
                hi = mid - 1

        return best_data, best_q
