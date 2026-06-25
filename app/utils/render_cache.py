"""
PDF Studio - 阅读器页面渲染 LRU 缓存
"""
from __future__ import annotations


class ReaderRenderCache:
    """按页缓存渲染结果，超出容量时淘汰最久未访问页。"""

    def __init__(self, max_size: int = 24) -> None:
        self._max_size = max(1, max_size)
        self._order: list[int] = []
        self._zoom_by_page: dict[int, float] = {}

    def __len__(self) -> int:
        return len(self._zoom_by_page)

    def is_valid(self, page_index: int, zoom: float, *, eps: float = 0.001) -> bool:
        cached = self._zoom_by_page.get(page_index)
        return cached is not None and abs(cached - zoom) <= eps

    def touch(self, page_index: int, zoom: float) -> list[int]:
        """登记页面已渲染，返回被淘汰的页索引。"""
        evicted: list[int] = []
        if page_index in self._zoom_by_page:
            self._order.remove(page_index)
        self._zoom_by_page[page_index] = zoom
        self._order.append(page_index)
        while len(self._order) > self._max_size:
            old = self._order.pop(0)
            if old in self._zoom_by_page:
                del self._zoom_by_page[old]
                evicted.append(old)
        return evicted

    def invalidate_pages(self, pages: set[int]) -> None:
        for page in pages:
            self._zoom_by_page.pop(page, None)
            if page in self._order:
                self._order.remove(page)

    def clear(self) -> list[int]:
        pages = list(self._zoom_by_page.keys())
        self._zoom_by_page.clear()
        self._order.clear()
        return pages
