@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在启动巨航剪辑工作台，浏览器会自动打开 http://127.0.0.1:8765
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8765"
.venv\Scripts\python.exe app.py
pause
