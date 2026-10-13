@echo off
setlocal
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto folder_unavailable
set "PULSE_PROJECT_DIR=%CD%"
if not exist "pyproject.toml" goto incomplete_archive
if not exist "uv.lock" goto incomplete_archive
if not exist "app\__init__.py" goto incomplete_archive
if not exist "app\desktop.py" goto incomplete_archive
if not exist "app\main.py" goto incomplete_archive
if not exist "app\static\index.html" goto incomplete_archive
echo Pornire PULSE din "%PULSE_PROJECT_DIR%"
where uv >nul 2>&1
if not errorlevel 1 goto run_uv
where py >nul 2>&1
if errorlevel 1 goto python_missing
py -m uv --version >nul 2>&1
if not errorlevel 1 goto run_python_uv
echo Instalare uv prin Python pip...
py -m pip install --user uv
set "PULSE_EXIT_CODE=%ERRORLEVEL%"
if not "%PULSE_EXIT_CODE%"=="0" goto finished

:run_python_uv
py -m uv run --directory "%PULSE_PROJECT_DIR%" --project "%PULSE_PROJECT_DIR%" --python 3.12 --frozen --no-dev python -m app.desktop
set "PULSE_EXIT_CODE=%ERRORLEVEL%"
goto finished

:run_uv
uv run --directory "%PULSE_PROJECT_DIR%" --project "%PULSE_PROJECT_DIR%" --python 3.12 --frozen --no-dev python -m app.desktop
set "PULSE_EXIT_CODE=%ERRORLEVEL%"

:finished
if "%PULSE_EXIT_CODE%"=="0" goto success
echo Pornirea a esuat. Pastreaza mesajul de eroare de mai sus.
pause
popd
exit /b %PULSE_EXIT_CODE%

:success
popd
exit /b 0

:incomplete_archive
echo.
echo Pachetul PULSE nu este extras complet in acest folder:
echo "%PULSE_PROJECT_DIR%"
echo.
echo Nu porni start-windows.cmd direct din arhiva ZIP.
echo 1. Inchide aceasta fereastra.
echo 2. Click dreapta pe chatgpt-main.zip si alege "Extrage tot...".
echo 3. Deschide folderul extras care contine app, pyproject.toml si uv.lock.
echo 4. Porneste start-windows.cmd din acel folder.
echo Daca ai copiat doar acest fisier, extrage intreaga arhiva.
pause
popd
exit /b 2

:python_missing
echo Instaleaza Python de pe python.org, cu Python launcher activat.
echo Apoi deschide din nou start-windows.cmd.
pause
popd
exit /b 1

:folder_unavailable
echo Folderul aplicatiei nu poate fi deschis. Extrage intreaga arhiva intr-un folder local.
pause
exit /b 2
