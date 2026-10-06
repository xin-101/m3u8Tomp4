# m3u8ToMp4

专业的 M3U8(HLS) 视频下载与 MP4 转换桌面客户端。

类似 IDM + 视频下载工具 + FFmpeg GUI。

## 功能特性

- ✅ M3U8 地址解析（Master/Media 播放列表、本地与网络）
- ✅ 视频信息展示（分辨率/码率/时长/音频/分片数）
- ✅ 多任务并发下载与队列管理
- ✅ 下载限速（令牌桶全局控制）
- ✅ 断点续传（分片级状态持久化，关闭后自动恢复）
- ✅ AES-128 解密支持（普通密钥），DRM 内容自动拦截
- ✅ FFmpeg 集成（`-c copy` 快速封装，失败自动回退 libx264/aac）
- ✅ 本地/网络 m3u8 → MP4/MKV 转换（本地免外部安装，`resources/ffmpeg.exe`）
- ✅ 多线程分片下载 + 暂停/恢复/重试
- ✅ 任务持久化 + 启动自动恢复未完成任务
- ✅ 历史记录（搜索/删除/打开目录/重新下载/清空）
- ✅ 深色现代 UI（PySide6）

## 技术栈

- Python 3.11+
- PySide6 (GUI)
- FFmpeg (视频处理)
- SQLite (任务/历史存储)
- PyInstaller (打包)

## 运行方法

```bash
pip install -r requirements.txt
# 确保 resources/ffmpeg.exe 存在(已将便携版内置, 或自行放置)
python main.py
```

## 测试

```bash
python tests/test_parser.py        # M3U8解析单元测试
python tests/test_integration.py   # FFmpeg/下载/限速/续传 集成测试
```

## 项目结构

```
m3u8ToMp4/
├── main.py                 # 程序入口
├── app/
│   ├── ui/                 # 界面层
│   │   ├── main_window.py  # 主窗口(信号接线/关闭保存)
│   │   ├── task_widget.py  # 任务列表页
│   │   ├── history_page.py # 历史记录页
│   │   ├── settings.py     # 设置对话框
│   │   └── parse_dialog.py # M3U8解析结果对话框
│   ├── core/               # 核心业务
│   │   ├── m3u8_parser.py  # M3U8解析(含DRM拦截)
│   │   ├── downloader.py   # 分片下载器(AES-128/续传/状态)
│   │   ├── task_manager.py # 任务队列调度
│   │   ├── ffmpeg_engine.py# FFmpeg引擎
│   │   └── speed_controller.py # 令牌桶限速
│   ├── database/           # SQLite数据层
│   └── browser/            # 浏览器插件(待实现)
├── resources/              # ffmpeg.exe等资源
├── logs/                   # 运行日志+数据库
├── download_cache/         # 断点续传缓存
├── tests/                  # 测试与夹具
├── requirements.txt
├── build.bat
└── README.md
```

## 开发阶段

- [x] Phase 1: 项目初始化(PySide6窗口/基础UI/项目结构)
- [x] Phase 2: M3U8解析
- [x] Phase 3: FFmpeg转换
- [x] Phase 4: 下载任务管理
- [x] Phase 5: 断点续传
- [x] Phase 6: 历史数据库
- [ ] Phase 7: 浏览器插件(API预留)
- [ ] Phase 8: 打包exe

## 日志

运行日志输出到 `logs/app.log`。
