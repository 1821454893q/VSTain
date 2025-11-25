"""设置页面组件"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    SubtitleLabel,
    setFont,
    PushButton,
    ComboBox,
    InfoBarIcon,
    SearchLineEdit,
    IconWidget,
    InfoBarIcon,
    BodyLabel,
    PrimaryPushButton,
    FluentIcon,
    GroupHeaderCardWidget,
)


class SettingsWidget(QWidget):
    """设置页面组件"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName(text)
        # self.setTitle("基本设置")
