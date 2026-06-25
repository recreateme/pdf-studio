"""
PDF Studio - 日志系统
基于 loguru 的结构化日志，支持文件轮转与控制台输出
"""
import sys
from pathlib import Path
from loguru import logger

from app.config.constants import LOGS_DIR


def setup_logger(level: str = "INFO") -> None:
    """
    初始化日志系统

    Args:
        level: 日志级别 DEBUG/INFO/WARNING/ERROR
    """
    # 移除默认处理器
    logger.remove()

    # ── 控制台输出（windowed 打包版 stderr 可能为 None）──
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

    # ── 文件输出（按天轮转，保留7天）────────────
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        LOGS_DIR / "pdf_studio_{time:YYYY-MM-DD}.log",
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}",
        rotation="00:00",          # 每天零点轮转
        retention="7 days",        # 保留7天
        compression="zip",         # 旧日志压缩
        encoding="utf-8",
        enqueue=True,              # 线程安全异步写入
    )

    # ── 错误专用文件 ──────────────────────────
    logger.add(
        LOGS_DIR / "errors.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line}\n{message}\n",
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )

    logger.info(f"日志系统初始化完成，级别: {level}")


# 导出 logger 供全局使用
__all__ = ["logger", "setup_logger"]
