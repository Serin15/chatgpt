@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if not errorlevel 1 (
    uv run --python 3.12 --frozen --no-dev python -m app.desktop
    goto finished
)
where py >nul 2>&1
if errorlevel 1 (
    echo Install Python from python.org, then open this file again.
    echo Enable the Python launcher during installation.
    pause
    exit /b 1
)
py -m uv --version >nul 2>&1
if errorlevel 1 (
    echo Installing the uv package manager through Python pip...
    py -m pip install --user uv
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
py -m uv run --python 3.12 --frozen --no-dev python -m app.desktop
:finished
if errorlevel 1 (
    echo Startup failed. Keep the error above to troubleshoot.
    pause
    exit /b 1
)
endlocal
