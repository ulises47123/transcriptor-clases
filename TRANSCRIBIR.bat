@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Transcribiendo todo lo que hay en la carpeta "entrada"...
echo (Se puede cerrar en cualquier momento: al volver a abrir, continua donde quedo)
echo.
python transcribir.py %*
echo.
pause
