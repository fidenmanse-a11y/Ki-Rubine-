@echo off
if not exist "%~dp0scripts\start.ps1" (
  echo.
  echo Diese Datei muss im Rubine-Ordner liegen, direkt neben den Ordnern "scripts", "backend" und "frontend".
  echo Aktueller Ort: %~dp0
  echo Bitte den kompletten Rubine-Ordner z. B. nach C:\Rubine verschieben und die Datei dort starten.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
pause
