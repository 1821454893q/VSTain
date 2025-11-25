"""应用配置"""

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# 资源目录
RESOURCE_DIR = PROJECT_ROOT / "resource"

# 日志目录
LOG_DIR = PROJECT_ROOT / "logs"

# 日志配置文件
LOG_CONFIG_FILE = PROJECT_ROOT / "logging_config.json"

# 项目配置文件
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"

# QAA 文件目录
QT_QSS_DIR = RESOURCE_DIR / "qss"

# 模型 文件目录
MODULES_DIR = RESOURCE_DIR / "modules"

# 窗口配置
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600
WINDOW_TITLE = "工具"
