import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.ui.main_window import MainWindow


def setup_logging() -> logging.Logger:
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("m3u8ToMp4")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        logs_dir / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def main() -> int:
    logger = setup_logging()
    logger.info("m3u8ToMp4 启动中...")
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)
        app.setApplicationName("m3u8ToMp4")
        app.setOrganizationName("m3u8ToMp4")
        window = MainWindow()
        window.show()
        logger.info("主窗口已显示")
        exit_code = app.exec()
        logger.info("程序退出, code=%s", exit_code)
        return exit_code
    except Exception:
        logger.exception("程序启动失败")
        raise


if __name__ == "__main__":
    sys.exit(main())
