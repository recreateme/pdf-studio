"""
PDF Studio - 通用工具函数集
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator, Iterable

from app.config.constants import TEMP_DIR


# ─────────────────────────────────────────────
# 文件工具
# ─────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    """确保目录存在，不存在则创建"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_file_size_str(path: str | Path) -> str:
    """返回人类可读的文件大小字符串"""
    size = Path(path).stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_unique_path(path: str | Path) -> Path:
    """
    若文件已存在，自动添加数字后缀
    例：output.pdf -> output_1.pdf -> output_2.pdf
    """
    p = Path(path)
    if not p.exists():
        return p
    stem = p.stem
    suffix = p.suffix
    parent = p.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def safe_filename(name: str) -> str:
    """移除文件名中的非法字符"""
    illegal = r'\/:*?"<>|'
    for ch in illegal:
        name = name.replace(ch, "_")
    return name.strip(". ")


def make_temp_file(suffix: str = ".tmp") -> Path:
    """创建临时文件，返回路径"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    return Path(path)


def make_temp_dir() -> Path:
    """创建临时目录，返回路径"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=TEMP_DIR))


def clean_temp() -> None:
    """清理全部临时文件"""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def file_md5(path: str | Path) -> str:
    """计算文件MD5（用于重复检测）"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(
    root: str | Path,
    extensions: Iterable[str],
    recursive: bool = True,
) -> list[Path]:
    """
    收集目录下指定扩展名的文件

    Args:
        root: 根目录
        extensions: 扩展名集合，如 {'.pdf', '.PDF'}
        recursive: 是否递归子目录

    Returns:
        按文件名排序的路径列表
    """
    root = Path(root)
    exts = {e.lower() for e in extensions}
    pattern = "**/*" if recursive else "*"
    results = [
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in exts
    ]
    return sorted(results, key=lambda p: p.name.lower())


# ─────────────────────────────────────────────
# 时间工具
# ─────────────────────────────────────────────

def now_str(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """返回当前时间格式化字符串，用于文件命名"""
    return datetime.now().strftime(fmt)


def elapsed_str(seconds: float) -> str:
    """将秒数格式化为 mm:ss 或 hh:mm:ss"""
    s = int(seconds)
    if s < 3600:
        return f"{s // 60:02d}:{s % 60:02d}"
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# ─────────────────────────────────────────────
# 系统工具
# ─────────────────────────────────────────────

def open_in_explorer(path: str | Path) -> None:
    """用系统文件管理器打开目录"""
    path = Path(path)
    target = path if path.is_dir() else path.parent
    if sys.platform == "win32":
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def open_file(path: str | Path) -> None:
    """用系统默认程序打开文件"""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def is_pdf_valid(path: str | Path) -> bool:
    """快速检查PDF文件头是否合法"""
    try:
        with open(path, "rb") as f:
            header = f.read(5)
        return header == b"%PDF-"
    except OSError:
        return False


# ─────────────────────────────────────────────
# 迭代工具
# ─────────────────────────────────────────────

def chunked(lst: list, n: int) -> Generator[list, None, None]:
    """将列表按 n 分块"""
    for i in range(0, len(lst), n):
        yield lst[i: i + n]
