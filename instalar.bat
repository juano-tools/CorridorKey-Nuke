@echo off
rem CorridorKey para Nuke: doble clic para instalar. Si Windows pregunta, elige "Mas informacion" y "Ejecutar de todos modos".
cd /d "%~dp0"
echo Instalando CorridorKey para Nuke. Tarda entre 10 y 30 minutos segun tu conexion; no cierres esta ventana.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
echo.
pause
