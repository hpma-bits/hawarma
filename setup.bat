@echo off
chcp 65001 >nul
title Hawarma 安装程序
echo ============================================
echo   Hawarma - 烹饪游戏自动化 Agent
echo   安装程序
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python
    echo.
    echo 请安装 Python 3.10 或更高版本：
    echo   https://www.python.org/downloads/
    echo.
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [OK] Python 已安装
python --version

:: 检查 Python 版本
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo.

:: 创建虚拟环境
echo [1/4] 创建虚拟环境...
if not exist ".venv" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)
echo [OK] 虚拟环境就绪

:: 安装 uv（如果没有）
echo [2/4] 检查 uv 包管理器...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 uv...
    pip install uv >nul 2>&1
)
echo [OK] uv 就绪

:: 安装依赖
echo [3/4] 安装项目依赖（可能需要几分钟）...
call .venv\Scripts\activate.bat
uv pip install -e . 2>&1
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，尝试使用 pip...
    pip install -e .
)
echo [OK] 依赖安装完成

:: 检查配置
echo [4/4] 检查配置文件...
if not exist "configs\config.yaml" (
    echo [警告] 未找到配置文件 configs\config.yaml
    echo 请确保在项目根目录运行此脚本
) else (
    echo [OK] 配置文件就绪
)

echo.
echo ============================================
echo   安装完成！
echo.
echo   启动方式：
echo     双击 run.bat    （TUI 图形界面）
echo     或运行命令：python -m hawarma
echo ============================================
pause