@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo MiniCraft needs uv for automatic setup.
    echo Install uv: https://docs.astral.sh/uv/getting-started/installation/
    echo Or follow the manual Python 3.12 instructions in README.md.
    pause
    exit /b 1
)
uv run --python 3.12 --with-requirements requirements.txt main.py %*
if errorlevel 1 (
    echo.
    echo MiniCraft could not start. See the error above.
    pause
    exit /b 1
)
