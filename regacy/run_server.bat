@echo off
cd /d "%~dp0"
echo. >> server.log
echo ========================================== >> server.log
echo [%date% %time%] Starting AI Chat Auto-Saver >> server.log
"C:\Users\tokut\AppData\Local\Programs\Python\Python314\python.exe" server.py >> server.log 2>&1
echo [%date% %time%] Server exited >> server.log
