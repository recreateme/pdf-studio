"""
PDF Studio - 运行时核心依赖检查
确保 PDF AES-256 加密等能力在正式使用时不会因缺包而静默失败。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    available: bool
    version: str = ""
    install_hint: str = ""
    required: bool = True
    feature: str = ""


INSTALL_HINT = (
    "请执行：pip install -r requirements.txt\n"
    "或仅安装加密依赖：pip install \"cryptography>=3.1\""
)


def check_cryptography() -> DependencyStatus:
    """检查 pypdf AES-256 所需的 cryptography 是否可用。"""
    try:
        import cryptography
        from cryptography.hazmat.primitives.ciphers.algorithms import AES  # noqa: F401
    except ImportError as exc:
        return DependencyStatus(
            name="cryptography",
            available=False,
            install_hint=INSTALL_HINT,
            version=str(exc),
        )
    return DependencyStatus(
        name="cryptography",
        available=True,
        version=getattr(cryptography, "__version__", "unknown"),
    )


def check_pdf_encrypt_provider() -> DependencyStatus:
    """确认 pypdf 已选用 cryptography 作为加密后端（非 fallback）。"""
    crypto = check_cryptography()
    if not crypto.available:
        return crypto
    try:
        from pypdf import crypt_provider
    except ImportError:
        # PyInstaller 打包时可能未导出 pypdf.crypt_provider，直接探测 cryptography 后端
        try:
            from pypdf._crypt_providers._cryptography import crypt_provider as cp  # type: ignore
        except ImportError as exc:
            return DependencyStatus(
                name="pypdf.crypt_provider",
                available=False,
                install_hint=INSTALL_HINT,
                version=str(exc),
            )
        provider_name = cp[0] if cp else ""
        version = cp[1] if cp and len(cp) > 1 else ""
    else:
        provider_name = crypt_provider[0] if crypt_provider else ""
        version = crypt_provider[1] if crypt_provider and len(crypt_provider) > 1 else ""
    if provider_name != "cryptography":
        return DependencyStatus(
            name="pypdf.crypt_provider",
            available=False,
            version=f"{provider_name} {version}".strip() or "unknown",
            install_hint=INSTALL_HINT,
        )
    return DependencyStatus(
        name="pypdf.crypt_provider",
        available=True,
        version=f"{provider_name} {version}".strip(),
    )


def verify_core_dependencies() -> list[DependencyStatus]:
    """返回未满足的核心依赖列表（空列表表示就绪）。"""
    missing: list[DependencyStatus] = []
    for checker in (check_cryptography, check_pdf_encrypt_provider):
        status = checker()
        if not status.available:
            missing.append(status)
    return missing


def ensure_pdf_encrypt_ready() -> None:
    """加密/解密前调用；未就绪时抛出带安装说明的 RuntimeError。"""
    missing = verify_core_dependencies()
    if not missing:
        return
    lines = ["PDF AES-256 加密依赖未就绪："]
    for item in missing:
        lines.append(f"  · {item.name}: {item.version or '不可用'}")
    lines.append("")
    lines.append(missing[0].install_hint or INSTALL_HINT)
    raise RuntimeError("\n".join(lines))


def format_missing_dependencies_message(missing: list[DependencyStatus]) -> str:
    if not missing:
        return ""
    lines = ["以下核心依赖未安装，部分功能将不可用："]
    for item in missing:
        lines.append(f"  · {item.name}")
    lines.append("")
    lines.append(missing[0].install_hint or INSTALL_HINT)
    return "\n".join(lines)


def check_pymupdf() -> DependencyStatus:
    try:
        import fitz
        ver = getattr(fitz, "mupdf_version", None) or getattr(fitz, "VersionBind", "ok")
        return DependencyStatus(
            name="PyMuPDF (fitz)",
            available=True,
            version=str(ver),
            required=True,
            feature="PDF 渲染与处理",
        )
    except ImportError as exc:
        return DependencyStatus(
            name="PyMuPDF (fitz)",
            available=False,
            version=str(exc),
            install_hint="pip install PyMuPDF",
            required=True,
            feature="PDF 渲染与处理",
        )


def check_playwright() -> DependencyStatus:
    try:
        import playwright
        version = getattr(playwright, "__version__", "installed")
    except ImportError:
        return DependencyStatus(
            name="Playwright",
            available=False,
            install_hint="pip install playwright\nplaywright install chromium",
            required=False,
            feature="网页转 PDF / 截图",
        )
    browser_hint = ""
    try:
        from pathlib import Path
        local_app = Path.home() / "AppData" / "Local"
        if any(local_app.glob("Google/Chrome/**")) or any(
            local_app.glob("Microsoft/Edge/**")
        ):
            browser_hint = " · 已检测到系统 Chrome/Edge 可作备选"
    except Exception:
        pass
    return DependencyStatus(
        name="Playwright",
        available=True,
        version=f"{version}{browser_hint}",
        required=False,
        feature="网页转 PDF / 截图",
    )


def check_ocr_engine() -> DependencyStatus:
    try:
        from core.ocr.engine import OCRManager
        manager = OCRManager()
        if manager.is_available:
            return DependencyStatus(
                name="RapidOCR",
                available=True,
                version="引擎就绪",
                required=False,
                feature="OCR 识别",
            )
        return DependencyStatus(
            name="RapidOCR",
            available=False,
            install_hint="pip install rapidocr-onnxruntime onnxruntime",
            required=False,
            feature="OCR 识别",
        )
    except Exception as exc:
        return DependencyStatus(
            name="RapidOCR",
            available=False,
            version=str(exc)[:60],
            install_hint="pip install rapidocr-onnxruntime onnxruntime",
            required=False,
            feature="OCR 识别",
        )


def get_setup_dependency_report() -> list[DependencyStatus]:
    """首次启动向导：必选 + 可选依赖一览。"""
    items: list[DependencyStatus] = [
        check_pymupdf(),
        check_cryptography(),
        check_pdf_encrypt_provider(),
        check_ocr_engine(),
        check_playwright(),
    ]
    seen: set[str] = set()
    unique: list[DependencyStatus] = []
    for item in items:
        if item.name in seen:
            continue
        seen.add(item.name)
        unique.append(item)
    return unique


def format_setup_install_commands(report: list[DependencyStatus]) -> str:
    """根据缺失项生成可复制的一键安装命令。"""
    missing_required = [r for r in report if r.required and not r.available]
    missing_optional = [r for r in report if not r.required and not r.available]

    lines = ["pip install -r requirements.txt"]
    if missing_required:
        names = {r.name for r in missing_required}
        if any("cryptography" in n for n in names):
            lines.append('pip install "cryptography>=3.1"')
    if missing_optional:
        opt_names = {r.name for r in missing_optional}
        if "RapidOCR" in opt_names:
            lines.append("pip install rapidocr-onnxruntime onnxruntime")
        if "Playwright" in opt_names:
            lines.append("pip install playwright")
            lines.append("playwright install chromium")
    lines.append("python scripts/ensure_deps.py --install")
    return "\n".join(lines)
