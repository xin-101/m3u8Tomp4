@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ========================================
echo   m3u8ToMp4 打包脚本 (Phase 8)
echo ========================================

if not exist "resources\ffmpeg.exe" (
  echo [错误] 缺少 resources\ffmpeg.exe, 请先将 ffmpeg 便携版放入 resources 目录
  echo        下载地址: https://www.gyan.dev/ffmpeg/builds/
  pause
  exit /b 1
)

where pyinstaller >nul 2>&1
if errorlevel 1 (
  echo 安装 PyInstaller...
  pip install pyinstaller
)

echo 开始 PyInstaller 打包(可能需要 3~8 分钟)...
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name m3u8ToMp4 ^
  --add-data "resources;resources" ^
  --add-data "browser-extension;browser-extension" ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  main.py

if errorlevel 1 (
  echo [错误] 打包失败
  pause
  exit /b 1
)

if not exist "release" mkdir release
copy /y dist\m3u8ToMp4.exe release\m3u8ToMp4.exe >nul
copy /y resources\ffmpeg.exe release\ffmpeg.exe >nul
if not exist "release\config" mkdir release\config

echo 复制说明文件...
(
  echo m3u8ToMp4 v1.0
  echo.
  echo 使用方法:
  echo   双击 m3u8ToMp4.exe 即可运行。
  echo   无需安装 Python, 无需额外安装 FFmpeg(ffmpeg.exe 已随包提供^)。
  echo.
  echo 功能:
  echo   - M3U8 解析 / 本地网络下载 / 合并 / 转换为 MP4 或 MKV
  echo   - 多任务队列、并发控制、下载限速
  echo   - 断点续传: 关闭后再次运行自动恢复未完成任务
  echo   - 历史记录、自动命名、AES-128 解密(普通密钥)、DRM 检测拦截
  echo   - 浏览器插件: 启动后客户端监听 127.0.0.1:18888, 插件可通过 API 发送任务
  echo.
  echo 目录说明:
  echo   config\\ 预留配置目录
  echo   logs\\    运行日志与历史数据库
) > release\README.txt

echo.
echo ========================================
echo 打包完成: release\m3u8ToMp4.exe
echo ========================================
pause
