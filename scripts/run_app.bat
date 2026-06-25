@echo off
REM PDF Studio 启动脚本（conda 环境 pdf-Assist）
set PY=D:\Software\MiniAnaconda\envs\pdf-Assist\python.exe
cd /d "%~dp0.."
echo [PDF Studio] 检查核心依赖...
"%PY%" scripts/ensure_deps.py --install
if errorlevel 1 (
    echo 依赖安装/检查失败，请手动运行: pip install -r requirements.txt
    pause
    exit /b 1
)
"%PY%" main.py
