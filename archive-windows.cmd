@echo off
setlocal
pushd "%~dp0" >nul 2>&1
if errorlevel 1 exit /b 2
if not exist "app\storage.py" goto incomplete
if not exist "uv.lock" goto incomplete
echo MemeScope: arhivare fara stergerea istoricului.
echo Inchide fereastra aplicatiei inainte de a continua.
echo Se pastreaza ultimele 7 zile necomprimate si ultima observatie pentru fiecare token.
echo Backupul este creat si restaurarea lui verificata inaintea modificarilor.
where uv >nul 2>&1
if errorlevel 1 goto python_uv
uv run --directory "%CD%" --project "%CD%" --python 3.12 --frozen --no-dev python -m app.storage archive --days 7 --compact
set "PULSE_STORAGE_EXIT=%ERRORLEVEL%"
goto done
:python_uv
py -m uv run --directory "%CD%" --project "%CD%" --python 3.12 --frozen --no-dev python -m app.storage archive --days 7 --compact
set "PULSE_STORAGE_EXIT=%ERRORLEVEL%"
:done
if not "%PULSE_STORAGE_EXIT%"=="0" echo Operatia s-a oprit. Pastreaza eroarea de mai sus; nu sterge baza sau backupurile.
if "%PULSE_STORAGE_EXIT%"=="0" echo Arhivare verificata. Poti porni start-windows.cmd.
pause
popd
exit /b %PULSE_STORAGE_EXIT%
:incomplete
echo Extrage intreaga arhiva MemeScope, apoi ruleaza acest fisier din folderul extras.
pause
popd
exit /b 2
