from __future__ import annotations

import logging
from pathlib import Path

from bridgecal.logging_config import NOISY_OAUTH_LOGGERS, configure_logging


def test_configure_logging_sets_oauth_loggers_to_warning(tmp_path: Path) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_root_level = root.level
    original_levels = {
        logger_name: logging.getLogger(logger_name).level for logger_name in NOISY_OAUTH_LOGGERS
    }

    try:
        configure_logging(tmp_path / "bridgecal.log", level="INFO")
        for logger_name in NOISY_OAUTH_LOGGERS:
            assert logging.getLogger(logger_name).level == logging.WARNING
    finally:
        current_root = logging.getLogger()
        for handler in list(current_root.handlers):
            current_root.removeHandler(handler)
        current_root.setLevel(original_root_level)
        for handler in original_handlers:
            current_root.addHandler(handler)
        for logger_name, level in original_levels.items():
            logging.getLogger(logger_name).setLevel(level)
