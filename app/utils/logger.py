"""
pd-studio - 轻量日志接口（不写文件、不创建 logs 目录）

保留 loguru.logger 以便各模块现有 logger.info/warning 调用无需改动；
默认不输出到文件，也不创建任何日志目录。
"""
from __future__ import annotations

from loguru import logger

# 移除 loguru 默认 stderr sink，避免无意输出；需要时可再由 setup_logger 挂接
logger.remove()


def setup_logger(level: str = "INFO") -> None:
    """
    初始化日志（无文件）。

    当前实现：清空所有 sink，不创建 logs 目录、不写任何日志文件。
    ``level`` 参数保留以兼容旧调用，但不会启用文件或控制台落盘。
    """
    del level  # 保留签名兼容
    logger.remove()


__all__ = ["logger", "setup_logger"]
