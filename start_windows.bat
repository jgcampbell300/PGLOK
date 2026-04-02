@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\check_env.py
  if errorlevel 1 goto :ask_install_venv
  ".venv\Scripts\python.exe" -m src.pglok
  goto :eof
)

if exist "build_env\Scripts\python.exe" (
  "build_env\Scripts\python.exe" scripts\check_env.py
  if errorlevel 1 goto :ask_install_build_env
  "build_env\Scripts\python.exe" -m src.pglok
  goto :eof
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 scripts\check_env.py
  if errorlevel 1 goto :ask_install_py
  py -3 -m src.pglok
  goto :eof
)

python scripts\check_env.py
if errorlevel 1 goto :ask_install_python
python -m src.pglok
goto :eof

:ask_install_venv
echo.
set /p ANSWER=Dependencies are missing. Install now? (Y/N): 
if /I "%ANSWER%"=="Y" (
  call install_windows.bat
  ".venv\Scripts\python.exe" scripts\check_env.py || goto :fail
  ".venv\Scripts\python.exe" -m src.pglok
  goto :eof
)
goto :cancel

:ask_install_build_env
echo.
set /p ANSWER=Dependencies are missing. Install now? (Y/N): 
if /I "%ANSWER%"=="Y" (
  call install_windows.bat
  "build_env\Scripts\python.exe" scripts\check_env.py || goto :fail
  "build_env\Scripts\python.exe" -m src.pglok
  goto :eof
)
goto :cancel

:ask_install_py
echo.
set /p ANSWER=Dependencies are missing. Install now? (Y/N): 
if /I "%ANSWER%"=="Y" (
  call install_windows.bat
  py -3 scripts\check_env.py || goto :fail
  py -3 -m src.pglok
  goto :eof
)
goto :cancel

:ask_install_python
echo.
set /p ANSWER=Dependencies are missing. Install now? (Y/N): 
if /I "%ANSWER%"=="Y" (
  call install_windows.bat
  python scripts\check_env.py || goto :fail
  python -m src.pglok
  goto :eof
)
goto :cancel

:cancel
echo Startup cancelled.
exit /b 1

:fail
echo.
echo Environment check failed after install attempt.
pause
exit /b 1
