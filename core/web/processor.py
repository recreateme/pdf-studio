"""
PDF Studio - 网页转PDF引擎
基于 Playwright + 内置 Chromium，无需额外浏览器
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.utils.logger import logger
from app.utils.helpers import get_unique_path


# ─────────────────────────────────────────────
# 数据类型
# ─────────────────────────────────────────────

@dataclass
class WebToPDFOptions:
    """网页转PDF选项"""
    output_path: Path
    wait_timeout: int = 30           # 页面加载超时(秒)
    wait_after_load: float = 2.0     # 加载完成后等待(秒，用于JS渲染)
    scroll_to_bottom: bool = True    # 是否滚动到底部（触发懒加载）
    max_scroll_times: int = 20       # 最大滚动次数
    scroll_wait: float = 0.5         # 每次滚动等待(秒)
    page_format: str = "A4"          # A4/A3/Letter/Legal
    margin_top: float = 10.0         # mm
    margin_bottom: float = 10.0
    margin_left: float = 10.0
    margin_right: float = 10.0
    print_background: bool = True
    enable_javascript: bool = True
    reading_mode: bool = False       # 阅读模式（移除广告/导航）
    cookie_file: Optional[Path] = None
    extra_headers: dict = field(default_factory=dict)
    viewport_width: int = 1280
    viewport_height: int = 900
    scale: float = 1.0               # PDF缩放比例


@dataclass
class WebToImageOptions:
    """网页截图选项"""
    output_path: Path
    full_page: bool = True           # 是否截取完整页面
    format: str = "PNG"
    quality: int = 90                # JPEG质量
    viewport_width: int = 1280
    viewport_height: int = 900
    wait_timeout: int = 30
    scroll_to_bottom: bool = True
    max_scroll_times: int = 20
    scroll_wait: float = 0.5
    scale: float = 1.0


# ─────────────────────────────────────────────
# 阅读模式 JS 脚本
# ─────────────────────────────────────────────

READING_MODE_SCRIPT = """
() => {
    // 移除广告、导航栏、弹窗等干扰元素
    const removeSelectors = [
        'nav', 'header', 'footer', 'aside',
        '[class*="ad"]', '[class*="banner"]', '[class*="popup"]',
        '[class*="modal"]', '[class*="overlay"]', '[class*="cookie"]',
        '[id*="ad"]', '[id*="banner"]', '[id*="modal"]',
        'script[type="text/javascript"]',
    ];
    removeSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            // 仅移除明显的非内容元素
            const style = window.getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                el.remove();
            }
        });
    });

    // 移除固定定位的覆盖层
    document.querySelectorAll('*').forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.position === 'fixed' || style.position === 'sticky') {
            const rect = el.getBoundingClientRect();
            if (rect.width > window.innerWidth * 0.5 || rect.height > window.innerHeight * 0.3) {
                el.remove();
            }
        }
    });
}
"""

SCROLL_SCRIPT = """
async (maxScrolls, scrollWaitMs) => {
    let lastHeight = 0;
    let scrollCount = 0;
    while (scrollCount < maxScrolls) {
        window.scrollBy(0, window.innerHeight);
        await new Promise(r => setTimeout(r, scrollWaitMs));
        const newHeight = document.body.scrollHeight;
        if (newHeight === lastHeight) break;
        lastHeight = newHeight;
        scrollCount++;
    }
    window.scrollTo(0, 0);
}
"""


# ─────────────────────────────────────────────
# 网页处理器
# ─────────────────────────────────────────────

class WebProcessor:
    """
    网页转PDF处理器
    使用 Playwright 异步API，在 QThread 中通过 asyncio.run() 调用
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    def is_playwright_available(self) -> bool:
        """检查 playwright 是否已安装且存在可用浏览器"""
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return (
            self._playwright_chromium_exists()
            or self._system_browser_exists()
        )

    @staticmethod
    def _playwright_chromium_exists() -> bool:
        """检测 Playwright 内置 Chromium 是否已下载"""
        import sys
        base = Path.home() / "AppData" / "Local" / "ms-playwright"
        if sys.platform != "win32":
            base = Path.home() / ".cache" / "ms-playwright"
        if not base.exists():
            return False
        return any(base.glob("chromium*/**/*.exe")) or any(
            base.glob("chromium_headless_shell*/**/*.exe")
        )

    @staticmethod
    def _system_browser_exists() -> bool:
        """检测系统是否安装 Chrome 或 Edge"""
        candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ]
        if sys.platform == "darwin":
            candidates = [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
        elif sys.platform != "win32":
            candidates = [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/chromium-browser"),
                Path("/usr/bin/microsoft-edge"),
            ]
        return any(p.exists() for p in candidates)

    async def _launch_browser(self, playwright, progress_cb=None):
        """
        启动浏览器：优先内置 Chromium，回退到系统 Chrome/Edge
        """
        errors: list[str] = []

        if self._playwright_chromium_exists():
            try:
                return await playwright.chromium.launch(headless=True)
            except Exception as e:
                errors.append(f"内置 Chromium: {e}")

        for channel in ("chrome", "msedge"):
            try:
                if progress_cb:
                    progress_cb(f"正在启动系统浏览器 ({channel})...")
                return await playwright.chromium.launch(channel=channel, headless=True)
            except Exception as e:
                errors.append(f"{channel}: {e}")

        hint = (
            "无法启动浏览器。请安装 Google Chrome / Microsoft Edge，"
            "或在 conda 环境 pdf-Assist 中运行：playwright install chromium"
        )
        if errors:
            hint += "\n详情：\n" + "\n".join(errors)
        raise RuntimeError(hint)

    # ── URL转PDF ──────────────────────────────

    def url_to_pdf(
        self,
        url: str,
        options: WebToPDFOptions,
        progress_cb: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        """
        将网页URL转换为PDF

        此方法在普通线程中调用，内部使用 asyncio.run() 运行异步代码

        Args:
            url: 目标URL
            options: 转换选项
            progress_cb: 状态回调（字符串消息）

        Returns:
            生成的PDF路径
        """
        output_path = Path(options.output_path)
        # 取消快速响应：不需要启动浏览器/下载资源
        if should_cancel and should_cancel():
            if cleanup_on_cancel:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
            return output_path

        return asyncio.run(
            self._url_to_pdf_async(
                url,
                options,
                progress_cb,
                should_cancel=should_cancel,
                cleanup_on_cancel=cleanup_on_cancel,
            )
        )

    async def _url_to_pdf_async(
        self,
        url: str,
        options: WebToPDFOptions,
        progress_cb: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        cleanup_on_cancel: bool = False,
    ) -> Path:
        from playwright.async_api import async_playwright

        if not self.is_playwright_available():
            raise RuntimeError(
                "未找到可用浏览器。请安装 Chrome/Edge，或运行：playwright install chromium"
            )

        output_path = Path(options.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = None
            page = None
            cancel_requested = False

            async def _monitor_cancel():
                nonlocal cancel_requested
                # 轮询频率越低响应越慢；这里取折中
                while True:
                    if should_cancel and should_cancel():
                        cancel_requested = True
                        # 尽可能中断当前等待/渲染
                        try:
                            if page is not None:
                                await page.close()
                        except Exception:
                            pass
                        try:
                            if browser is not None:
                                await browser.close()
                        except Exception:
                            pass
                        return
                    await asyncio.sleep(0.2)

            monitor_task = None
            if should_cancel is not None:
                monitor_task = asyncio.create_task(_monitor_cancel())

            try:
                if progress_cb:
                    progress_cb("正在启动浏览器...")
                browser = await self._launch_browser(p, progress_cb)
                context_kwargs = {
                    "viewport": {
                        "width": options.viewport_width,
                        "height": options.viewport_height,
                    },
                    "java_script_enabled": options.enable_javascript,
                }

                # 加载 Cookie
                if options.cookie_file and Path(options.cookie_file).exists():
                    import json
                    cookies = json.loads(Path(options.cookie_file).read_text())
                    context_kwargs["storage_state"] = {"cookies": cookies}

                context = await browser.new_context(**context_kwargs)

                # 额外请求头
                if options.extra_headers:
                    await context.set_extra_http_headers(options.extra_headers)

                page = await context.new_page()

                if progress_cb:
                    progress_cb(f"正在加载页面: {url}")

                if cancel_requested:
                    raise asyncio.CancelledError()

                await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=options.wait_timeout * 1000,
                )

                # 等待JS渲染
                if options.wait_after_load > 0:
                    await asyncio.sleep(options.wait_after_load)

                if cancel_requested:
                    raise asyncio.CancelledError()

                # 懒加载：滚动触发
                if options.scroll_to_bottom:
                    if progress_cb:
                        progress_cb("正在滚动加载内容...")
                    await page.evaluate(
                        SCROLL_SCRIPT,
                        [options.max_scroll_times, int(options.scroll_wait * 1000)],
                    )

                # 阅读模式
                if options.reading_mode:
                    await page.evaluate(READING_MODE_SCRIPT)

                if progress_cb:
                    progress_cb("正在生成PDF...")

                if cancel_requested:
                    raise asyncio.CancelledError()

                # 生成PDF
                await page.pdf(
                    path=str(output_path),
                    format=options.page_format,
                    margin={
                        "top": f"{options.margin_top}mm",
                        "bottom": f"{options.margin_bottom}mm",
                        "left": f"{options.margin_left}mm",
                        "right": f"{options.margin_right}mm",
                    },
                    print_background=options.print_background,
                    scale=options.scale,
                )
            except asyncio.CancelledError:
                cancel_requested = True
            except Exception:
                # 取消过程中（例如浏览器被关闭导致的异常）也按取消处理
                if cancel_requested or (should_cancel and should_cancel()):
                    cancel_requested = True
                else:
                    raise
            finally:
                if monitor_task is not None:
                    monitor_task.cancel()
                try:
                    if page is not None:
                        await page.close()
                except Exception:
                    pass
                try:
                    if browser is not None:
                        await browser.close()
                except Exception:
                    pass

        if cancel_requested:
            if cleanup_on_cancel:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
            # 不抛异常，让 BaseWorker 发 cancelled 信号后由 UI 处理
            return output_path

        logger.info(f"网页转PDF完成: {url} -> {output_path.name}")
        return output_path

    # ── URL转截图 ─────────────────────────────

    def url_to_screenshot(
        self,
        url: str,
        options: WebToImageOptions,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """将网页转为长截图"""
        return asyncio.run(self._screenshot_async(url, options, progress_cb))

    async def _screenshot_async(
        self,
        url: str,
        options: WebToImageOptions,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Path:
        from playwright.async_api import async_playwright

        output_path = Path(options.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await self._launch_browser(p, progress_cb)
            page = await browser.new_page(viewport={
                "width": options.viewport_width,
                "height": options.viewport_height,
            })

            if progress_cb:
                progress_cb(f"加载页面: {url}")

            await page.goto(url, wait_until="networkidle", timeout=options.wait_timeout * 1000)

            if options.scroll_to_bottom:
                await page.evaluate(
                    SCROLL_SCRIPT,
                    [options.max_scroll_times, int(options.scroll_wait * 1000)],
                )

            if progress_cb:
                progress_cb("正在截图...")

            screenshot_kwargs = {
                "path": str(output_path),
                "full_page": options.full_page,
                "scale": "device",
            }
            if options.format.upper() == "JPEG":
                screenshot_kwargs["type"] = "jpeg"
                screenshot_kwargs["quality"] = options.quality

            await page.screenshot(**screenshot_kwargs)
            await browser.close()

        logger.info(f"网页截图完成: {url} -> {output_path.name}")
        return output_path

    # ── 批量处理 ──────────────────────────────

    def batch_urls_to_pdf(
        self,
        urls: list[str],
        output_dir: Path,
        base_options: WebToPDFOptions,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        *,
        max_workers: int | None = None,
    ) -> list[tuple[str, Path | Exception]]:
        """
        批量 URL 转 PDF（支持有限并行，每任务独立浏览器实例）

        Returns:
            [(url, Path | Exception)] 结果列表（顺序与 urls 一致）
        """
        if not urls:
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from dataclasses import replace
        from urllib.parse import urlparse

        from app.config.settings import settings_mgr
        from app.utils.helpers import safe_filename

        if max_workers is None:
            max_workers = settings_mgr.web.batch_concurrency
        max_workers = max(1, min(max_workers, 4, len(urls)))

        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[tuple[str, Path | Exception] | None] = [None] * len(urls)
        completed = 0

        def _convert_one(idx: int, url: str) -> tuple[int, str, Path | Exception]:
            if should_cancel and should_cancel():
                return idx, url, RuntimeError("已取消")
            parsed = urlparse(url)
            name = safe_filename(f"{parsed.netloc}{parsed.path}")[:80] or f"page_{idx + 1}"
            out_path = output_dir / f"{name}.pdf"
            opts = replace(base_options, output_path=get_unique_path(out_path))
            try:
                result_path = self.url_to_pdf(
                    url,
                    opts,
                    should_cancel=should_cancel,
                    cleanup_on_cancel=True,
                )
                logger.info(f"批处理 [{idx + 1}/{len(urls)}]: {url}")
                return idx, url, result_path
            except Exception as e:
                logger.error(f"批处理失败 [{idx + 1}/{len(urls)}] {url}: {e}")
                return idx, url, e

        if max_workers == 1:
            for idx, url in enumerate(urls):
                if should_cancel and should_cancel():
                    break
                i, u, res = _convert_one(idx, url)
                results[i] = (u, res)
                completed += 1
                if progress_cb:
                    progress_cb(completed, len(urls), u)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_convert_one, idx, url): idx
                    for idx, url in enumerate(urls)
                }
                for future in as_completed(futures):
                    if should_cancel and should_cancel():
                        for f in futures:
                            f.cancel()
                        break
                    idx, url, res = future.result()
                    results[idx] = (url, res)
                    completed += 1
                    if progress_cb:
                        progress_cb(completed, len(urls), url)

        return [r for r in results if r is not None]
