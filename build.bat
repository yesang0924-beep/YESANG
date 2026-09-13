@echo off
rem Relay Console 一键打包：生成 dist\RelayConsole.exe
cd /d %~dp0
rem Python 解释器：优先项目 venv，其次 PATH
set PY=venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo [1/3] 确保 PyInstaller 就绪...
%PY% -m pip show pyinstaller >nul 2>&1 || %PY% -m pip install pyinstaller -q

echo [2/3] PyInstaller 打包中（约 1-3 分钟）...
%PY% -m PyInstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo [FAIL] 打包失败，检查上方报错
    pause
    exit /b 1
)

echo [3/3] 完成
echo.
echo   输出: %~dp0dist\RelayConsole.exe
echo   双击即可运行，无需 Python 环境
pause
