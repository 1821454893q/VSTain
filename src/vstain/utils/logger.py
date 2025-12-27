import logging
from gas.simple_logger import create_logger, SimpleLogger
from src.vstain.common.settings import LOG_CONFIG_FILE, LOG_DIR, PYPROJECT_FILE

# 全局实例
_log_instance: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _log_instance
    if _log_instance is None:
        _log_instance = create_logger(
            project_name="vstain",
            log_dir=LOG_DIR,
            config_file=LOG_CONFIG_FILE,
            pyproject_file=PYPROJECT_FILE,
            initial_level="DEBUG",
        )
    return _log_instance
