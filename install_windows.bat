@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  goto :done
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m pip install --upgrade pip
  py -3 -m pip install -r requirements.txt
  goto :done
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

:done
echo Dependencies installed.
