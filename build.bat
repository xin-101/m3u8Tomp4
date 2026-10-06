@echo off
chcp 65001 >nul
echo ========================================
echo   m3u8ToMp4 打包脚本 (Phase 8)
echo ========================================

pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed ^
  --name m3u8ToMp4 ^
  --icon resources\app.ico ^
  --add-data "resources;resources" ^
  main.py

echo.
echo 打包完成: dist\m3u8ToMp4.exe
pause
