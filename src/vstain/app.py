"""应用入口"""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from qfluentwidgets import Theme, setTheme

from .windows import MainWindow
from src.vstain.common.config import cfg


def create_app() -> QApplication:
    """创建并配置应用"""
    # 设置高DPI缩放策略
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    # 创建应用
    app = QApplication(sys.argv)

    # 设置主题
    setTheme(cfg.get(cfg.themeMode))
    return app


def main():
    """主函数"""
    app = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
