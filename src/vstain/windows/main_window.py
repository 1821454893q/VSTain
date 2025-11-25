"""主窗口"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QScreen
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import (
    MSFluentWindow,
    NavigationItemPosition,
    isDarkTheme,
    setTheme,
    Theme,
)
from qfluentwidgets import FluentIcon as FIF, SystemThemeListener

from vstain.widgets.annotation_widget import AnnotationWidget
from src.vstain.config.settings import WINDOW_HEIGHT, WINDOW_TITLE, WINDOW_WIDTH
from src.vstain.widgets import HomeWidget, SettingsWidget, WindowFeatureCaptureWidget
from src.vstain.common.config import cfg

from src.vstain.utils.logger import get_logger

log = get_logger()


class MainWindow(MSFluentWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        # create system theme listener
        self.themeListener = SystemThemeListener(self)

        self.initNavigation()
        self.initWindow()

        self.themeListener.start()

    def initNavigation(self):
        """初始化导航"""
        # 创建子界面
        self.homeInterface = HomeWidget("Home Interface", self)
        self.annotationInterface = AnnotationWidget("annotation Interface", self)
        self.settingsInterface = SettingsWidget("Setting Interface", self)
        self.featureCaptureInterface = WindowFeatureCaptureWidget("teatureCapture Interface", self)

        self.addSubInterface(self.homeInterface, FIF.HOME, "主页", FIF.HOME_FILL)
        self.addSubInterface(self.annotationInterface, FIF.TAG, "图片标注")
        self.addSubInterface(self.featureCaptureInterface, FIF.PAUSE, "特征捕获")

        self.navigationInterface.addItem(
            routeKey="theme",
            icon=FIF.BRIGHTNESS,
            text="主题",
            onClick=self.switchTheme,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )

        self.addSubInterface(
            self.settingsInterface,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

        self.navigationInterface.setCurrentItem(self.homeInterface.objectName())

    def initWindow(self):
        """初始化窗口"""
        [x, y, width, height] = cfg.get(cfg.main_windows_position)
        self.setWindowIcon(QIcon(":/qfluentwidgets/images/logo.png"))
        self.setWindowTitle(WINDOW_TITLE)

        desktop = QApplication.desktop().availableGeometry()
        if x == 0 and y == 0:
            self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
            w, h = desktop.width(), desktop.height()
            x2, y2 = w // 2 - self.width() // 2, h // 2 - self.height() // 2
            self.move(x2, y2)
            cfg.set(cfg.main_windows_position, [x2, y2, WINDOW_WIDTH, WINDOW_HEIGHT])
        else:
            self.resize(width, height)
            self.move(x, y)

    def switchTheme(self):
        """切换主题"""
        if isDarkTheme():
            setTheme(Theme.LIGHT, True)
        else:
            setTheme(Theme.DARK, True)

    def closeEvent(self, e):
        log.debug("closeEvent")
        self.themeListener.terminate()
        self.themeListener.deleteLater()
        super().closeEvent(e)
