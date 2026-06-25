"""
安装并验证 PDF Studio 核心依赖（尤其 cryptography / PDF 加密）。
用法：python scripts/ensure_deps.py [--install]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
CRYPTO_SPEC = "cryptography>=3.1"


def _pip_install(*packages: str) -> None:
    cmd = [sys.executable, "-m", "pip", "install", *packages]
    print("执行:", " ".join(cmd))
    subprocess.check_call(cmd)


def _verify() -> bool:
    sys.path.insert(0, str(ROOT))
    from app.utils.deps import verify_core_dependencies

    missing = verify_core_dependencies()
    if missing:
        print("依赖检查失败:")
        for item in missing:
            print(f"  - {item.name}: {item.version or 'missing'}")
        return False
    from app.utils.deps import check_cryptography, check_pdf_encrypt_provider

    crypto = check_cryptography()
    provider = check_pdf_encrypt_provider()
    print(f"OK  cryptography {crypto.version}")
    print(f"OK  pypdf provider {provider.version}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure PDF Studio core dependencies")
    parser.add_argument(
        "--install",
        action="store_true",
        help="缺失时自动 pip install（默认：requirements.txt + cryptography）",
    )
    args = parser.parse_args()

    if _verify():
        return 0

    if not args.install:
        print("\n请运行: python scripts/ensure_deps.py --install")
        print("或: pip install -r requirements.txt")
        return 1

    if REQUIREMENTS.is_file():
        _pip_install("-r", str(REQUIREMENTS))
    else:
        _pip_install(CRYPTO_SPEC)

    if _verify():
        return 0
    _pip_install(CRYPTO_SPEC)
    return 0 if _verify() else 1


if __name__ == "__main__":
    raise SystemExit(main())
