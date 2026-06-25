@echo off
REM PDF Studio 测试脚本（conda 环境 pdf-Assist）
set PY=D:\Software\MiniAnaconda\envs\pdf-Assist\python.exe
cd /d "%~dp0.."
echo [PDF Studio] 检查核心依赖...
"%PY%" scripts/ensure_deps.py --install
if errorlevel 1 (
    echo 依赖安装/检查失败，请手动运行: pip install -r requirements-dev.txt
    exit /b 1
)
echo [PDF Studio] 安装/检查开发测试依赖...
"%PY%" -m pip install -q -r requirements-dev.txt
if errorlevel 1 (
    echo 开发依赖安装失败，请手动运行: pip install -r requirements-dev.txt
    exit /b 1
)
"%PY%" -m pytest tests/ -v --tb=short %*
