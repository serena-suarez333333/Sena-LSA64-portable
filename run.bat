@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
	echo No se encontro el lanzador de Python.
	echo Instala Python 3.10, 3.11 o 3.12 de 64 bits con el Python Launcher.
	pause
	exit /b 1
)

py -3.11 --version >nul 2>nul
if not errorlevel 1 (
	py -3.11 "%~dp0launch.py"
	exit /b %errorlevel%
)

py -3.12 --version >nul 2>nul
if not errorlevel 1 (
	py -3.12 "%~dp0launch.py"
	exit /b %errorlevel%
)

py -3.10 --version >nul 2>nul
if not errorlevel 1 (
	py -3.10 "%~dp0launch.py"
	exit /b %errorlevel%
)

echo Se requiere Python 3.10, 3.11 o 3.12 de 64 bits.
pause
exit /b 1
