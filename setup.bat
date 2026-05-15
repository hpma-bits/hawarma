@echo off
chcp 65001 >nul
title Hawarma 安装程序
echo ============================================
echo   Hawarma - 正在安装依赖...
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 创建虚拟环境
echo [1/3] 创建虚拟环境...
if not exist ".venv" (
    python -m venv .venv
)

:: 激活并安装依赖
echo [2/3] 安装依赖...
call .venv\Scripts\activate.bat
pip install -e . >nul 2>&1

:: 检查配置
echo [3/3] 检查配置文件...
if not exist "configs\config.yaml" (
    echo [警告] 未找到配置文件
)

echo.
echo ============================================
echo   安装完成！双击 run.bat 即可启动
echo ============================================
pause
