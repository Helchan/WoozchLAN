@echo off
setlocal EnableExtensions

cd /d %~dp0

if not "%~1"=="" (
  set "GOMOKU_LAN_DATA_DIR=%USERPROFILE%\.gomoku_lan_profiles\%~1"
  if not exist "%GOMOKU_LAN_DATA_DIR%" mkdir "%GOMOKU_LAN_DATA_DIR%" >nul 2>nul
)

set "PY="
py -3.12 -c "import tkinter" >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3.12"
) else (
  py -3 -c "import tkinter" >nul 2>nul
  if %errorlevel%==0 (
    set "PY=py -3"
  ) else (
    python -c "import tkinter" >nul 2>nul
    if %errorlevel%==0 (
      set "PY=python"
    )
  )
)

if "%PY%"=="" (
  echo 找不到可用的 Python（或缺少 Tkinter）。
  echo 1) 请安装 Python 3.12
  echo 2) 安装时勾选 Tcl/Tk（Tkinter）组件
  pause
  exit /b 1
)

goto RUN

if "%PY%"=="" (
  echo c|set /p="[31m"
  echo Python feffc|set /p=""
  echo.
  echo [0m
c|set /p=""
  echo 1) cbe0 Python 3.12
  echo 2) e0 e6 Tk28f92f7b4fe02
  pause
  exit /b 1
)

:RUN
%PY% main.py
endlocal
