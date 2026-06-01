@echo off
cd /d "%~dp0"
echo. >> sync.log
echo [%date% %time%] sync start >> sync.log
"C:\Users\tokut\AppData\Local\Programs\Python\Python314\python.exe" -u sync_all.py >> sync.log 2>&1
echo [%date% %time%] sync end >> sync.log