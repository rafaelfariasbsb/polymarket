@echo off
REM Polymarket Scalp Radar v2 - Windows Setup
setlocal

echo === Polymarket Scalp Radar v2 - Windows Setup ===
echo.

REM Detect Python
py --version >nul 2>&1
if %errorlevel% neq 0 goto nopython

REM Get version
for /f "tokens=2 delims= " %%v in ('py --version 2^>^&1') do set PY_FULL=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_FULL%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if %PY_MAJOR% lss 3 goto oldpython
if %PY_MAJOR%==3 if %PY_MINOR% lss 10 goto oldpython

echo [OK] Python %PY_FULL%
goto pythonok

:nopython
echo.
echo [ERROR] Python not found!
echo.
echo   To fix:
echo     1. Download Python 3.10+ from https://www.python.org/downloads/
echo     2. Run the installer and CHECK "Add python.exe to PATH"
echo     3. Disable the Windows Store alias:
echo        Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo        Turn OFF "python.exe" and "python3.exe"
echo     4. Close and reopen the terminal
echo     5. Run this setup again: .\setup.bat
echo.
pause
exit /b 1

:oldpython
echo [ERROR] Python 3.10+ required (found %PY_FULL%)
pause
exit /b 1

:pythonok

REM Create virtual environment
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    py -m venv venv
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
py -c "from dotenv import load_dotenv; from py_clob_client.client import ClobClient; from web3 import Web3; from eth_account import Account; import requests; print('[OK] All imports working')"
if %errorlevel% neq 0 (
    echo [!!] Some imports failed. Try: venv\Scripts\activate.bat then pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo === Setup complete ===
echo.
echo Usage:
echo   venv\Scripts\activate.bat
echo   py radar_poly.py          # default $4 trades
echo   py radar_poly.py 10       # $10 trades
echo.
pause
