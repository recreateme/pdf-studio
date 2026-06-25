"""
PDF Studio - 应用配置模型
使用 Pydantic v2 进行配置验证与管理
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# 子配置模型
# ─────────────────────────────────────────────

class GeneralSettings(BaseModel):
    """通用设置"""
    theme: Literal["light", "dark", "auto"] = "auto"
    language: Literal["zh_CN", "en_US", "ja_JP"] = "zh_CN"
    max_recent_files: int = Field(default=20, ge=5, le=100)
    auto_save_logs: bool = True
    check_updates: bool = False          # 离线模式默认关闭
    show_toolbar_labels: bool = True
    window_width: int = Field(default=1280, ge=800)
    window_height: int = Field(default=800, ge=600)
    setup_wizard_completed: bool = False
    window_maximized: bool = False


class PDFSettings(BaseModel):
    """PDF处理设置"""
    default_dpi: int = Field(default=150, ge=72, le=600)
    thumbnail_size: int = Field(default=160, ge=80, le=320)
    compression_level: Literal["high_quality", "balanced", "max_compress"] = "balanced"
    default_output_dir: str = ""          # 空字符串表示与源文件同目录
    jpeg_quality: int = Field(default=85, ge=10, le=100)
    enable_page_cache: bool = True
    cache_max_pages: int = Field(default=50, ge=10, le=500)


class OCRSettings(BaseModel):
    """OCR识别设置"""
    engine: Literal["rapidocr", "paddleocr"] = "rapidocr"
    languages: list[str] = ["ch", "en"]
    use_gpu: bool = False
    default_dpi: int = Field(default=200, ge=72, le=400)
    det_model_path: str = ""
    rec_model_path: str = ""
    cls_model_path: str = ""
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    output_format: Literal["txt", "docx", "markdown", "json", "searchable_pdf"] = "txt"
    auto_rotate: bool = True


class WebSettings(BaseModel):
    """网页转PDF设置"""
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    wait_timeout: int = Field(default=30, ge=5, le=300)        # 页面加载超时(秒)
    scroll_wait: float = Field(default=0.5, ge=0.1, le=5.0)   # 滚动等待(秒)
    max_scroll_times: int = Field(default=20, ge=1, le=100)
    page_format: Literal["A4", "A3", "Letter", "Legal"] = "A4"
    margin_top: float = 10.0       # mm
    margin_bottom: float = 10.0
    margin_left: float = 10.0
    margin_right: float = 10.0
    print_background: bool = True
    enable_javascript: bool = True
    cookie_file: str = ""
    batch_concurrency: int = Field(default=2, ge=1, le=4)


class WorkflowSettings(BaseModel):
    """批处理工作流设置"""
    max_workers: int = Field(default=4, ge=1, le=16)
    queue_max_size: int = Field(default=100, ge=10, le=1000)
    auto_retry_on_failure: bool = True
    retry_count: int = Field(default=3, ge=1, le=10)
    save_workflow_history: bool = True


class LogSettings(BaseModel):
    """日志设置"""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_file_size: str = "10 MB"
    retention: str = "7 days"
    log_dir: str = "logs"


class ReaderSettings(BaseModel):
    """阅读批注视图偏好"""
    fit_mode: Literal["fit_width", "fit_height", "actual", "fixed"] = "fit_width"
    fixed_zoom: float = Field(default=1.0, ge=0.25, le=4.0)
    layout_mode: Literal["single", "dual"] = "single"
    sidebar_width: int = Field(default=240, ge=160, le=480)


# ─────────────────────────────────────────────
# 主配置模型
# ─────────────────────────────────────────────

class AppSettings(BaseModel):
    """PDF Studio 主配置"""
    version: str = "1.0.0"
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    pdf: PDFSettings = Field(default_factory=PDFSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    reader: ReaderSettings = Field(default_factory=ReaderSettings)
    recent_files: list[str] = Field(default_factory=list)

    @field_validator("recent_files")
    @classmethod
    def validate_recent_files(cls, v: list[str]) -> list[str]:
        """过滤不存在的最近文件"""
        return [f for f in v if Path(f).exists()]


# ─────────────────────────────────────────────
# 配置管理器
# ─────────────────────────────────────────────

class SettingsManager:
    """
    配置管理器 - 单例模式
    负责配置的读取、保存与访问
    """
    _instance: Optional["SettingsManager"] = None
    _settings: Optional[AppSettings] = None

    CONFIG_DIR = Path.home() / ".pdf_studio"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __new__(cls) -> "SettingsManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._settings is None:
            self._settings = self._load()

    # ── 读写 ──────────────────────────────────

    def _load(self) -> AppSettings:
        """从磁盘加载配置，文件不存在则返回默认值"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if self.CONFIG_FILE.exists():
            try:
                raw = json.loads(self.CONFIG_FILE.read_text(encoding="utf-8"))
                return AppSettings(**raw)
            except Exception:
                return AppSettings()
        return AppSettings()

    def save(self) -> None:
        """将当前配置持久化到磁盘"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.CONFIG_FILE.write_text(
            self._settings.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def reset_to_defaults(self) -> None:
        """恢复默认配置并写入磁盘"""
        self._settings = AppSettings()
        self.save()

    def apply_runtime_settings(self) -> None:
        """应用需立即生效的运行时配置（日志级别、线程池等）"""
        from app.utils.logger import setup_logger

        setup_logger(self.log.level)
        try:
            from PyQt6.QtCore import QThreadPool

            QThreadPool.globalInstance().setMaxThreadCount(self.workflow.max_workers)
        except Exception:
            pass

    def resolve_output_dir(self, source_path: str | Path | None = None) -> Path:
        """
        解析默认输出目录。
        若设置了全局输出目录则使用之，否则回退到源文件所在目录。
        """
        configured = self.pdf.default_output_dir.strip()
        if configured:
            path = Path(configured)
            path.mkdir(parents=True, exist_ok=True)
            return path
        if source_path:
            return Path(source_path).parent
        docs = Path.home() / "Documents"
        docs.mkdir(parents=True, exist_ok=True)
        return docs

    def task_output_dir(
        self,
        source_path: str | Path,
        suffix: str = "",
    ) -> Path:
        """基于源文件与全局输出目录生成任务输出路径（可选子目录后缀）"""
        source_path = Path(source_path)
        base = self.resolve_output_dir(source_path)
        if self.pdf.default_output_dir.strip():
            out = base / f"{source_path.stem}{suffix}" if suffix else base
        else:
            out = source_path.parent / f"{source_path.stem}{suffix}" if suffix else source_path.parent
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ── 访问接口 ─────────────────────────────

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def general(self) -> GeneralSettings:
        return self._settings.general

    @property
    def pdf(self) -> PDFSettings:
        return self._settings.pdf

    @property
    def ocr(self) -> OCRSettings:
        return self._settings.ocr

    @property
    def web(self) -> WebSettings:
        return self._settings.web

    @property
    def workflow(self) -> WorkflowSettings:
        return self._settings.workflow

    @property
    def log(self) -> LogSettings:
        return self._settings.log

    @property
    def reader(self) -> ReaderSettings:
        return self._settings.reader

    # ── 最近文件管理 ─────────────────────────

    def add_recent_file(self, path: str) -> None:
        files = self._settings.recent_files
        if path in files:
            files.remove(path)
        files.insert(0, path)
        self._settings.recent_files = files[: self._settings.general.max_recent_files]
        self.save()

    def clear_recent_files(self) -> None:
        self._settings.recent_files = []
        self.save()

    # ── 工厂方法 ─────────────────────────────

    @classmethod
    def get_instance(cls) -> "SettingsManager":
        return cls()


# 模块级快捷访问
settings_mgr = SettingsManager.get_instance()
