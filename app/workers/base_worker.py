"""
PDF Studio - Worker 基础框架
基于 QThread + QRunnable，确保后台处理不阻塞UI
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QObject, QRunnable, QThread, QThreadPool,
    pyqtSignal, pyqtSlot,
)

from app.utils.logger import logger
from app.utils.task_hub import TaskHub


# ─────────────────────────────────────────────
# 通用信号集
# ─────────────────────────────────────────────

class WorkerSignals(QObject):
    """Worker 发出的标准信号集"""

    # 任务开始
    started = pyqtSignal()
    # 进度更新 (current, total)
    progress = pyqtSignal(int, int)
    # 状态消息
    message = pyqtSignal(str)
    # 任务完成，携带结果
    finished = pyqtSignal(object)
    # 任务失败，携带错误信息
    error = pyqtSignal(str)
    # 任务取消
    cancelled = pyqtSignal()


# ─────────────────────────────────────────────
# 基础 Worker
# ─────────────────────────────────────────────

class BaseWorker(QRunnable):
    """
    QRunnable-based Worker 基类

    子类只需覆盖 run_task() 方法。
    支持取消请求（通过 request_cancel()）。

    用法：
        worker = SomePDFWorker(...)
        worker.signals.progress.connect(self.update_progress)
        worker.signals.finished.connect(self.on_done)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._cancel_requested = False
        self.setAutoDelete(True)

    # ── 取消接口 ──────────────────────────────

    def request_cancel(self) -> None:
        """请求取消任务（子类在循环中检查 is_cancelled()）"""
        self._cancel_requested = True
        logger.debug(f"{self.__class__.__name__} 收到取消请求")

    def is_cancelled(self) -> bool:
        return self._cancel_requested

    # ── 进度/消息 helper ──────────────────────

    def emit_progress(self, current: int, total: int) -> None:
        self.signals.progress.emit(current, total)

    def emit_message(self, msg: str) -> None:
        self.signals.message.emit(msg)
        logger.debug(f"[{self.__class__.__name__}] {msg}")

    # ── QRunnable 入口 ────────────────────────

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self.run_task()
            if self._cancel_requested:
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(result)
        except Exception as e:
            logger.exception(f"{self.__class__.__name__} 执行失败")
            self.signals.error.emit(str(e))

    def run_task(self) -> Any:
        """子类实现实际任务逻辑，返回结果将通过 finished 信号传递"""
        raise NotImplementedError


# ─────────────────────────────────────────────
# 具体 Worker 实现
# ─────────────────────────────────────────────

class ThumbnailWorker(BaseWorker):
    """批量生成PDF缩略图"""

    def __init__(
        self,
        pdf_path: str,
        page_indices: list[int],
        width: int = 160,
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.page_indices = page_indices
        self.width = width
        self.password = password

    def run_task(self) -> list[tuple[int, bytes]]:
        """返回 [(page_index, png_bytes), ...]"""
        from core.pdf.processor import PDFReader as PDFReaderUtil
        results = []
        total = len(self.page_indices)

        for idx, page_idx in enumerate(self.page_indices):
            if self.is_cancelled():
                break
            try:
                data = PDFReaderUtil.render_thumbnail(
                    self.pdf_path, page_idx, self.width, self.password
                )
                results.append((page_idx, data))
            except Exception as e:
                logger.warning(f"缩略图生成失败 (页{page_idx}): {e}")

            self.emit_progress(idx + 1, total)

        return results


class PDFSplitWorker(BaseWorker):
    """PDF拆分Worker（按页面范围）"""

    def __init__(self, pdf_path: str, ranges: list, options) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.ranges = ranges
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFSplitter
        splitter = PDFSplitter()
        return splitter.split_by_ranges(
            self.pdf_path,
            self.ranges,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFSplitByCountWorker(BaseWorker):
    """PDF拆分Worker（按固定页数）"""

    def __init__(self, pdf_path: str, pages_per_file: int, options) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.pages_per_file = pages_per_file
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFSplitter
        return PDFSplitter().split_by_count(
            self.pdf_path,
            self.pages_per_file,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFSplitBySizeWorker(BaseWorker):
    """PDF拆分Worker（按文件大小）"""

    def __init__(self, pdf_path: str, max_size_mb: float, options) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.max_size_mb = max_size_mb
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFSplitter
        return PDFSplitter().split_by_size(
            self.pdf_path,
            self.max_size_mb,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFSplitByBookmarkWorker(BaseWorker):
    """PDF拆分Worker（按书签）"""

    def __init__(self, pdf_path: str, level: int, options) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.level = level
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFSplitter
        return PDFSplitter().split_by_bookmarks(
            self.pdf_path,
            self.options,
            self.level,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFSplitByBlankWorker(BaseWorker):
    """PDF拆分Worker（按空白页）"""

    def __init__(self, pdf_path: str, options) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFSplitter
        return PDFSplitter().split_by_blank_pages(
            self.pdf_path,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFMergeWorker(BaseWorker):
    """PDF合并Worker"""

    def __init__(self, paths: list[str], options) -> None:
        super().__init__()
        self.paths = paths
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFMerger
        merger = PDFMerger()
        return merger.merge(
            self.paths,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFCompressWorker(BaseWorker):
    """PDF压缩Worker"""

    def __init__(self, path: str, options) -> None:
        super().__init__()
        self.path = path
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFCompressor
        compressor = PDFCompressor()
        return compressor.compress(
            self.path,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFToImageWorker(BaseWorker):
    """PDF转图片Worker"""

    def __init__(self, path: str, options) -> None:
        super().__init__()
        self.path = path
        self.options = options

    def run_task(self):
        from core.image.converter import PDFToImageConverter
        converter = PDFToImageConverter()
        return converter.convert(
            self.path,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFLongImageWorker(BaseWorker):
    """PDF 导出长图 Worker"""

    def __init__(self, path: str, output_path: str, options) -> None:
        super().__init__()
        self.path = path
        self.output_path = output_path
        self.options = options

    def run_task(self):
        from core.image.converter import PDFToImageConverter
        return PDFToImageConverter().pdf_to_long_image(
            self.path,
            self.output_path,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
        )


class ImageToPDFWorker(BaseWorker):
    """图片转PDF Worker"""

    def __init__(self, paths: list[str], options) -> None:
        super().__init__()
        self.paths = paths
        self.options = options

    def run_task(self):
        from core.image.converter import ImageToPDFConverter
        converter = ImageToPDFConverter()
        return converter.convert(
            self.paths,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class ImageMergeWorker(BaseWorker):
    """多图合并 Worker"""

    def __init__(self, paths: list[str], options) -> None:
        super().__init__()
        self.paths = paths
        self.options = options

    def run_task(self):
        from core.image.merger import ImageMerger
        return ImageMerger().merge(
            self.paths,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
        )


class ImageMergePreviewWorker(BaseWorker):
    """图片合并预览 Worker（返回 PNG 字节）"""

    def __init__(self, paths: list[str], options) -> None:
        super().__init__()
        self.paths = paths
        self.options = options

    def run_task(self):
        import io

        from core.image.merger import ImageMerger
        canvas = ImageMerger().render_preview(self.paths, self.options)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


class OCRWorker(BaseWorker):
    """OCR识别Worker"""

    def __init__(self, path: str, options, is_pdf: bool = True) -> None:
        super().__init__()
        self.path = path
        self.options = options
        self.is_pdf = is_pdf

    def run_task(self):
        from core.ocr.engine import OCRManager
        from app.config.settings import settings_mgr
        manager = OCRManager(engine_name=settings_mgr.ocr.engine)

        if self.is_pdf:
            return manager.ocr_pdf(
                self.path,
                self.options,
                progress_cb=self.emit_progress,
                should_cancel=self.is_cancelled,
            )
        else:
            return [manager.ocr_image(self.path, self.options)]


class WebToPDFWorker(BaseWorker):
    """网页转PDF Worker"""

    def __init__(self, url: str, options) -> None:
        super().__init__()
        self.url = url
        self.options = options

    def run_task(self):
        from core.web.processor import WebProcessor
        processor = WebProcessor()
        return processor.url_to_pdf(
            self.url,
            self.options,
            progress_cb=self.emit_message,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class WatermarkWorker(BaseWorker):
    """水印添加Worker（文字 / 图片）"""

    def __init__(self, path: str, output_path: str, options) -> None:
        super().__init__()
        self.path = path
        self.output_path = output_path
        self.options = options

    def run_task(self):
        from core.pdf.processor import PDFWatermarker
        wm = PDFWatermarker()
        if self.options.image_path:
            return wm.add_image_watermark(
                self.path,
                self.output_path,
                self.options,
                progress_cb=self.emit_progress,
                should_cancel=self.is_cancelled,
                cleanup_on_cancel=True,
            )
        return wm.add_text_watermark(
            self.path,
            self.output_path,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
            cleanup_on_cancel=True,
        )


class PDFPageManageWorker(BaseWorker):
    """PDF 页面管理 Worker（提取 / 删除 / 旋转 / 插入空白 / 复制）"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        action: str,
        page_indices: list[int],
        rotate_angle: int = 90,
        blank_count: int = 1,
        after_page_index: int = -1,
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.action = action
        self.page_indices = page_indices
        self.rotate_angle = rotate_angle
        self.blank_count = blank_count
        self.after_page_index = after_page_index

    def run_task(self):
        from core.pdf.processor import PDFPageEditor, PDFSplitter
        if self.action == "extract":
            return PDFSplitter().extract_pages(
                self.pdf_path, self.page_indices, self.output_path
            )
        if self.action == "delete":
            return PDFPageEditor().delete_pages(
                self.pdf_path, self.output_path, self.page_indices
            )
        if self.action == "rotate":
            angles = {idx: self.rotate_angle for idx in self.page_indices}
            return PDFPageEditor().rotate_pages(
                self.pdf_path, self.output_path, angles
            )
        if self.action == "insert_blank":
            return PDFPageEditor().insert_blank_pages(
                self.pdf_path,
                self.output_path,
                self.after_page_index,
                self.blank_count,
            )
        if self.action == "duplicate":
            return PDFPageEditor().duplicate_pages(
                self.pdf_path, self.output_path, self.page_indices
            )
        raise ValueError(f"未知操作: {self.action}")


class PDFExtractTextWorker(BaseWorker):
    """提取 PDF 文字 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        page_indices: Optional[list[int]] = None,
        combined: bool = True,
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.page_indices = page_indices
        self.combined = combined

    def run_task(self):
        from core.pdf.processor import PDFContentExtractor
        return PDFContentExtractor().extract_text(
            self.pdf_path,
            self.output_dir,
            self.page_indices,
            combined=self.combined,
            progress_cb=self.emit_progress,
        )


class PDFExtractImagesWorker(BaseWorker):
    """提取 PDF 内嵌图片 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        page_indices: Optional[list[int]] = None,
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.page_indices = page_indices

    def run_task(self):
        from core.pdf.processor import PDFContentExtractor
        return PDFContentExtractor().extract_images(
            self.pdf_path,
            self.output_dir,
            self.page_indices,
            progress_cb=self.emit_progress,
        )


class PDFPageRenderWorker(BaseWorker):
    """渲染单页 PDF 为 PNG"""

    def __init__(
        self,
        pdf_path: str,
        page_index: int,
        zoom: float = 1.0,
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.page_index = page_index
        self.zoom = zoom
        self.password = password

    def run_task(self):
        from core.pdf.viewer import PDFViewerService
        return PDFViewerService.render_page(
            self.pdf_path, self.page_index, self.zoom, self.password
        )


class PDFSearchWorker(BaseWorker):
    """PDF 全文搜索 Worker"""

    def __init__(self, pdf_path: str, query: str, password: str = "") -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.query = query
        self.password = password

    def run_task(self):
        from core.pdf.viewer import PDFViewerService
        return PDFViewerService.search_text(
            self.pdf_path, self.query, self.password
        )


class PDFWatermarkDetectWorker(BaseWorker):
    """检测 PDF 疑似水印"""

    def __init__(self, pdf_path: str, password: str = "") -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFWatermarkRemover
        return PDFWatermarkRemover().detect_candidates(
            self.pdf_path, self.password
        )


class PDFWatermarkRemoveWorker(BaseWorker):
    """移除 PDF 水印"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        image_xrefs: list[int],
        text_patterns: list[str],
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.image_xrefs = image_xrefs
        self.text_patterns = text_patterns
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFWatermarkRemover
        return PDFWatermarkRemover().remove(
            self.pdf_path,
            self.output_path,
            image_xrefs=self.image_xrefs,
            text_patterns=self.text_patterns,
            password=self.password,
            progress_cb=self.emit_progress,
        )


class PDFFormListWorker(BaseWorker):
    """扫描 PDF 表单字段"""

    def __init__(self, pdf_path: str, password: str = "") -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFFormService
        return PDFFormService().list_fields(self.pdf_path, self.password)


class PDFFormFillWorker(BaseWorker):
    """填写 PDF 表单"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        field_values: dict[str, str],
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.field_values = field_values
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFFormService
        return PDFFormService().fill(
            self.pdf_path,
            self.output_path,
            self.field_values,
            self.password,
        )


class PDFSignatureWorker(BaseWorker):
    """插入图片签名"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        options,
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.options = options
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFSignatureService
        return PDFSignatureService().add_image_signature(
            self.pdf_path,
            self.output_path,
            self.options,
            self.password,
        )


class WebToImageWorker(BaseWorker):
    """网页截图 Worker"""

    def __init__(self, url: str, options) -> None:
        super().__init__()
        self.url = url
        self.options = options

    def run_task(self):
        from core.web.processor import WebProcessor
        processor = WebProcessor()
        return processor.url_to_screenshot(
            self.url,
            self.options,
            progress_cb=self.emit_message,
        )


class PDFRedactWorker(BaseWorker):
    """PDF 涂黑脱敏 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        regions: list,
        text_patterns: list[str],
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.regions = regions
        self.text_patterns = text_patterns
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFRedactionService
        return PDFRedactionService().apply_redactions(
            self.pdf_path,
            self.output_path,
            regions=self.regions,
            text_patterns=self.text_patterns,
            password=self.password,
            progress_cb=self.emit_progress,
        )


class ImageEnhanceWorker(BaseWorker):
    """扫描件 / 图片批量增强 Worker"""

    def __init__(
        self,
        input_paths: list[str],
        output_dir: str,
        options,
    ) -> None:
        super().__init__()
        self.input_paths = input_paths
        self.output_dir = output_dir
        self.options = options

    def run_task(self):
        from core.image.converter import ImageEnhancer
        return ImageEnhancer().enhance_batch(
            self.input_paths,
            self.output_dir,
            self.options,
            progress_cb=self.emit_progress,
        )


class ImageCompressWorker(BaseWorker):
    """图片批量压缩 Worker"""

    def __init__(self, input_paths: list[str], options) -> None:
        super().__init__()
        self.input_paths = input_paths
        self.options = options

    def run_task(self):
        from core.image.compressor import ImageCompressor
        return ImageCompressor().compress_batch(
            self.input_paths,
            self.options,
            progress_cb=self.emit_progress,
            should_cancel=self.is_cancelled,
        )


class PDFSaveAnnotationsWorker(BaseWorker):
    """保存 PDF 批注 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        annotations: list,
        password: str = "",
        delete_xrefs: list[int] | None = None,
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.annotations = annotations
        self.password = password
        self.delete_xrefs = delete_xrefs or []

    def run_task(self):
        from core.pdf.annotations import PDFAnnotationService
        return PDFAnnotationService().save_with_annotations(
            self.pdf_path,
            self.output_path,
            self.annotations,
            self.password,
            delete_xrefs=self.delete_xrefs,
        )


class PDFTextOverlayWorker(BaseWorker):
    """PDF 打字机文本叠加 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        items: list,
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.items = items
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFTextOverlayService
        return PDFTextOverlayService().add_text_overlays(
            self.pdf_path,
            self.output_path,
            self.items,
            password=self.password,
        )


class PDFMetadataWorker(BaseWorker):
    """PDF 元数据编辑 Worker"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str,
        *,
        title: str = "",
        author: str = "",
        subject: str = "",
        keywords: str = "",
        password: str = "",
    ) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.title = title
        self.author = author
        self.subject = subject
        self.keywords = keywords
        self.password = password

    def run_task(self):
        from core.pdf.extras import PDFMetadataService
        return PDFMetadataService().update_metadata(
            self.pdf_path,
            self.output_path,
            title=self.title,
            author=self.author,
            subject=self.subject,
            keywords=self.keywords,
            password=self.password,
        )


# ─────────────────────────────────────────────
# 全局线程池访问
# ─────────────────────────────────────────────

def get_thread_pool() -> QThreadPool:
    """返回全局线程池（单例）"""
    pool = QThreadPool.globalInstance()
    try:
        from app.config.settings import settings_mgr
        pool.setMaxThreadCount(settings_mgr.workflow.max_workers)
    except Exception:
        pool.setMaxThreadCount(8)
    return pool


_QUIET_WORKERS = frozenset({"ThumbnailWorker", "PDFPageRenderWorker"})


def submit_worker(worker: BaseWorker, task_label: str = "") -> bool:
    """
    提交 Worker 到全局线程池，并注册到任务中心（预览类任务除外）。

    Returns:
        True 已接受；False 队列已满被拒绝（调用方可提示用户）
    """
    if worker.__class__.__name__ in _QUIET_WORKERS:
        get_thread_pool().start(worker)
        return True

    from app.config.settings import settings_mgr

    wf = settings_mgr.workflow
    hub = TaskHub.instance()
    label = task_label or getattr(worker, "task_label", "")
    return hub.submit(
        worker,
        label or worker.__class__.__name__.replace("Worker", ""),
        max_concurrent=wf.max_workers,
        max_total=wf.queue_max_size,
    )
