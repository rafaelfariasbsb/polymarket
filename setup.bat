@echo off
REM Polymarket Scalp Radar v2 - Windows Setup
setlocal

echo === Polymarket Scalp Radar v2 - Windows Setup ===
echo.

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.major)"') do set PY_MAJOR=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.minor)"') do set PY_MINOR=%%i

if %PY_MAJOR% lss 3 (
    echo [ERROR] Python 3.10+ required (found %PY_VERSION%)
    pause
    exit /b 1
)
if %PY_MAJOR% equ 3 if %PY_MINOR% lss 10 (
    echo [ERROR] Python 3.10+ required (found %PY_VERSION%)
    pause
    exit /b 1
)
echo [OK] Python %PY_VERSION%

REM Create virtual environment
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)

REM Activate and install dependencies
echo.
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo [OK] Dependencies installed

REM Setup .env
if not exist ".env" (
    echo.
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [!!] Created .env from .env.example
        echo      Edit .env and add your POLYMARKET_API_KEY before running.
    ) else (
        echo [!!] No .env file found. Create one with your POLYMARKET_API_KEY.
    )
) else (
    echo [OK] .env exists
)

REM Verify imports
echo.
echo Verifying imports...
call venv\Scripts\activate.bat
python -c "from dotenv import load_dotenv; from py_clob_client.client import ClobClient; from web3 import Web3; from eth_account import Account; import requests; print('[OK] All imports working')"
if %errorlevel% neq 0 (
    echo [!!] Some imports failed. Try: venv\Scripts\activate.bat ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo === Setup complete ===
echo.
echo Usage:
echo   venv\Scripts\activate.bat
echo   python radar_scalp.py          # default $4 trades
echo   python radar_scalp.py 10       # $10 trades
echo.
pause
