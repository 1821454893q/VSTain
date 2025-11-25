"""平台相关工具函数"""
import sys


def is_win11() -> bool:
    """检查是否为 Windows 11"""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000

