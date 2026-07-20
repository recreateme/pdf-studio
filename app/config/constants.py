"""
PDF Studio - 应用常量
集中管理颜色、尺寸、字符串等全局常量
"""
from pathlib import Path

# ─────────────────────────────────────────────
# 应用信息
# ─────────────────────────────────────────────
APP_NAME = "pd-studio"
APP_VERSION = "1.0.0"
APP_AUTHOR = "1299800632@qq.com"
APP_CONTACT = "1299800632@qq.com"
APP_WINDOW_TITLE = "pd-studio 1299800632@qq.com"
APP_DESCRIPTION = "WPS 免费版 PDF 工具箱补位 · 本地离线 · 无广告"
APP_HOMEPAGE = "https://github.com/recreateme/pdf-studio"

# 各功能页 WPS 对标说明（副标题旁注）
PAGE_WPS_HINTS: dict[str, str] = {
    "split": "补位 WPS 会员：PDF 拆分",
    "merge": "补位 WPS 会员：PDF 合并",
    "compare": "补位 WPS 会员：PDF 对比",
    "pages": "补位 WPS 会员：提取 / 删除页面",
    "compress": "补位 WPS 会员：PDF 压缩",
    "encrypt": "补位 WPS 会员：加密与权限",
    "watermark": "补位 WPS 会员：水印与页码",
    "tools": "补位 WPS 会员：去水印 · 表单 · 签名 · 涂黑",
    "image": "补位 WPS 会员：PDF 转图片 · 长图/拼图合并 · 扫描增强",
    "ocr": "补位 WPS 会员：OCR 文字识别",
    "web": "网页采集：转 PDF / 长截图",
    "reader": "配合 WPS 免费阅读：深度批注与保存",
}

OUTPUT_VIEW_HINT = "可在 WPS 或本应用「阅读批注」中继续查看"

# 首页快捷卡片 WPS 对标标注（route key → 徽章文案，空串表示不显示）
DASHBOARD_WPS_BADGES: dict[str, str] = {
    "split": "WPS 会员 · 本地免费",
    "merge": "WPS 会员 · 本地免费",
    "compare": "WPS 会员 · 本地免费",
    "pages": "WPS 会员 · 本地免费",
    "compress": "WPS 会员 · 本地免费",
    "encrypt": "WPS 会员 · 本地免费",
    "tools": "WPS 会员 · 本地免费",
    "image": "WPS 会员 · 本地免费",
    "ocr": "WPS 会员 · 本地免费",
    "reader": "配合 WPS 免费阅读",
}

# ─────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent.parent        # pdf_studio/
APP_DIR = ROOT_DIR / "app"
CORE_DIR = ROOT_DIR / "core"
RESOURCES_DIR = APP_DIR / "resources"
ICONS_DIR = RESOURCES_DIR / "icons"
FONTS_DIR = RESOURCES_DIR / "fonts"
CACHE_DIR = ROOT_DIR / "cache"
LOGS_DIR = ROOT_DIR / "logs"
TEMP_DIR = CACHE_DIR / "temp"

# 用户数据目录（跨平台）
import sys
if sys.platform == "win32":
    USER_DATA_DIR = Path.home() / "AppData" / "Local" / "PDFStudio"
elif sys.platform == "darwin":
    USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "PDFStudio"
else:
    USER_DATA_DIR = Path.home() / ".local" / "share" / "pdf_studio"

# ─────────────────────────────────────────────
# 窗口尺寸
# ─────────────────────────────────────────────
MAIN_WINDOW_MIN_WIDTH = 900
MAIN_WINDOW_MIN_HEIGHT = 650
MAIN_WINDOW_DEFAULT_WIDTH = 1280
MAIN_WINDOW_DEFAULT_HEIGHT = 800
NAV_WIDTH = 220
NAV_COLLAPSED_WIDTH = 60

# ─────────────────────────────────────────────
# PDF处理限制
# ─────────────────────────────────────────────
MAX_PDF_SIZE_MB = 2048          # 最大文件大小 2GB
MAX_PAGES_PREVIEW = 500         # 拆分/缩略图面板等非阅读器场景的建议上限
READER_RENDER_BUFFER = 2        # 阅读器视口上下额外预渲染页数
READER_RENDER_CACHE_MAX = 24    # 阅读器 LRU 渲染缓存页数上限
READER_ZOOM_WHEEL_STEP = 0.1    # Ctrl+滚轮缩放步进（相对比例）
READER_DUAL_GAP = 16            # 双页并排间距（px）
READER_LAYOUT_SPACING = 8       # 阅读区块间距（px）
READER_THUMB_BATCH = 40         # 缩略图分批加载数量
READER_PLACEHOLDER_HEIGHT = 720 # 未渲染页的占位高度（px）
THUMBNAIL_WIDTH = 160
THUMBNAIL_HEIGHT = 220
DEFAULT_DPI = 150


def get_default_dpi() -> int:
    """从用户设置读取默认渲染 DPI"""
    try:
        from app.config.settings import settings_mgr
        return settings_mgr.pdf.default_dpi
    except Exception:
        return DEFAULT_DPI


def get_thumbnail_width() -> int:
    """从用户设置读取缩略图宽度"""
    try:
        from app.config.settings import settings_mgr
        return settings_mgr.pdf.thumbnail_size
    except Exception:
        return THUMBNAIL_WIDTH


def get_thumbnail_height() -> int:
    """按宽度等比计算缩略图高度"""
    w = get_thumbnail_width()
    return max(110, int(w * THUMBNAIL_HEIGHT / THUMBNAIL_WIDTH))
PREVIEW_DPI = 96
EXPORT_DPI_MIN = 72
EXPORT_DPI_MAX = 600

# ─────────────────────────────────────────────
# 线程池配置
# ─────────────────────────────────────────────
MAX_THREAD_WORKERS = 8
THUMBNAIL_BATCH_SIZE = 10       # 每批加载缩略图数量

# ─────────────────────────────────────────────
# 支持的文件格式
# ─────────────────────────────────────────────
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif"}
SUPPORTED_IMPORT_EXTENSIONS = SUPPORTED_PDF_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS

IMAGE_EXPORT_FORMATS = ["PNG", "JPEG", "WEBP", "TIFF", "BMP"]
OCR_OUTPUT_FORMATS = ["TXT", "DOCX", "Markdown", "JSON", "可搜索PDF"]

# ─────────────────────────────────────────────
# OCR语言映射
# ─────────────────────────────────────────────
OCR_LANGUAGE_MAP = {
    "中文": "ch",
    "英文": "en",
    "日文": "japan",
    "韩文": "korean",
    "法文": "french",
    "德文": "german",
}

# ─────────────────────────────────────────────
# 网页转PDF
# ─────────────────────────────────────────────
WEB_PAGE_FORMATS = {
    "A4": (794, 1123),    # px at 96dpi
    "A3": (1123, 1587),
    "Letter": (816, 1056),
    "Legal": (816, 1344),
}

# ─────────────────────────────────────────────
# UI样式常量
# ─────────────────────────────────────────────
# Fluent Design 主题色
THEME_COLOR_LIGHT = "#0078D4"    # Windows 蓝
THEME_COLOR_DARK = "#60CDFF"

# 状态颜色
COLOR_SUCCESS = "#107C10"
COLOR_WARNING = "#FF8C00"
COLOR_ERROR = "#C42B1C"
COLOR_INFO = "#0078D4"

# 缩略图占位符颜色
THUMBNAIL_PLACEHOLDER_BG = "#F0F0F0"
THUMBNAIL_PLACEHOLDER_DARK_BG = "#2D2D2D"

# ─────────────────────────────────────────────
# 信号/槽消息类型
# ─────────────────────────────────────────────
MSG_TYPE_INFO = "info"
MSG_TYPE_SUCCESS = "success"
MSG_TYPE_WARNING = "warning"
MSG_TYPE_ERROR = "error"

# ─────────────────────────────────────────────
# 工作流任务类型
# ─────────────────────────────────────────────
TASK_PDF_SPLIT = "pdf_split"
TASK_PDF_MERGE = "pdf_merge"
TASK_PDF_COMPRESS = "pdf_compress"
TASK_PDF_ENCRYPT = "pdf_encrypt"
TASK_PDF_TO_IMAGE = "pdf_to_image"
TASK_IMAGE_TO_PDF = "image_to_pdf"
TASK_OCR = "ocr"
TASK_WEB_TO_PDF = "web_to_pdf"
TASK_WATERMARK = "watermark"
TASK_PAGE_NUMBER = "page_number"
