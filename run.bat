@echo off
chcp 65001 >nul
title Hawarma - 烹饪游戏自动化

:: 检查虚拟环境
if not exist ".venv" (
    echo [错误] 未找到虚拟环境，请先运行 setup.bat
    pause
    exit /b 1
)

:: 启动 TUI
call .venv\Scripts\activate.bat
python -m hawarma.tui
pause