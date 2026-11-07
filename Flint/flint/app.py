from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .ui.main_window import MainWindow

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def _setup_logging(debug: bool) -> None:
    logger = logging.getLogger("flint")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / "flint.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("???????? %s????????", LOG_DIR)


def _install_excepthook() -> None:
    logger = logging.getLogger("flint")

    def hook(exc_type, exc_value, exc_tb) -> None:
        logger.exception("?????", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def run(debug: bool = False) -> int:
    _setup_logging(debug)
    _install_excepthook()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    return app.exec()
