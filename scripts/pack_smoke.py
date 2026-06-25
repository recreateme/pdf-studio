#!/usr/bin/env python3
"""
PDF Studio 打包冒烟：依赖检查 → pytest → PyInstaller → 冻结包 --pack-smoke → 可选 GUI 启动探测

用法（项目根目录）：
  python scripts/pack_smoke.py
  python scripts/pack_smoke.py --skip-build
  python scripts/pack_smoke.py --skip-pytest
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)
DIST_EXE = ROOT / "dist" / "PDFStudio" / "PDFStudio.exe"


def _resolve_dist_exe(dist_dir: Path | None) -> Path:
    if dist_dir is not None:
        return dist_dir / "PDFStudio.exe"
    return DIST_EXE


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)


def _check_dist_layout(dist_exe: Path) -> None:
    if not dist_exe.is_file():
        raise SystemExit(f"未找到 {dist_exe}")
    internal = dist_exe.parent / "_internal"
    for name in ("fitz", "cryptography"):
        hits = list(internal.rglob(f"{name}*"))
        if not hits and name == "fitz":
            # fitz 可能以 pymupdf 形式存在
            hits = list(internal.rglob("pymupdf*"))
        if not hits:
            raise SystemExit(f"_internal 缺少 {name} 相关模块")
    icons = list(internal.rglob("app.ico")) + list(internal.rglob("app.png"))
    if not icons:
        raise SystemExit("_internal 未包含 app 图标资源")
    print(f"  dist OK: {dist_exe} ({dist_exe.stat().st_size // 1024} KB)")


def _probe_gui_launch(dist_exe: Path, timeout_sec: float = 6.0) -> bool:
    """短暂启动 GUI，进程仍存活视为启动成功。"""
    proc = subprocess.Popen(
        [str(dist_exe)],
        cwd=dist_exe.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(timeout_sec)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"  GUI 启动探测 OK（{timeout_sec}s 内未崩溃）")
        return True
    print(f"  GUI 过早退出，exit code={proc.returncode}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF Studio 打包冒烟")
    parser.add_argument("--skip-build", action="store_true", help="跳过 PyInstaller，仅验收已有 dist")
    parser.add_argument("--skip-pytest", action="store_true", help="跳过 pytest")
    parser.add_argument("--no-gui-probe", action="store_true", help="跳过 GUI 短暂启动探测")
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="打包输出目录（默认 dist/PDFStudio）",
    )
    args = parser.parse_args()

    dist_exe = _resolve_dist_exe(args.dist_dir)

    print("=== PDF Studio 打包冒烟 ===\n")

    _run([str(PY), "scripts/ensure_deps.py", "--install"])

    if not args.skip_pytest:
        _run([str(PY), "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"])
        _run([str(PY), "-m", "pytest", "tests/", "-q", "--tb=line"])

    ico = ROOT / "app" / "resources" / "icons" / "app.ico"
    if not ico.is_file():
        _run([str(PY), "scripts/generate_app_icon.py"])

    if not args.skip_build:
        _run([
            str(PY),
            "-m",
            "PyInstaller",
            "pdf_studio.spec",
            "--noconfirm",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
        ])

    _check_dist_layout(dist_exe)

    _run([str(dist_exe), "--pack-smoke"], cwd=dist_exe.parent)
    result_file = dist_exe.parent / "pack_smoke_result.txt"
    if not result_file.is_file():
        raise SystemExit(f"未生成结果文件: {result_file}")
    content = result_file.read_text(encoding="utf-8").strip()
    print(f"  pack-smoke 结果: {content}")
    if not content.startswith("OK:"):
        raise SystemExit(f"冻结包冒烟失败: {content}")

    if not args.no_gui_probe and not _probe_gui_launch(dist_exe):
        print(f"  警告: GUI 自动探测未通过，请手动双击验收: {dist_exe}")

    print("\n=== 打包冒烟通过 ===")
    print(f"输出目录: {dist_exe.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
