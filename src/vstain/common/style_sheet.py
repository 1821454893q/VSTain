# coding: utf-8
from enum import Enum

from qfluentwidgets import StyleSheetBase, Theme, isDarkTheme, qconfig

from vstain.config.settings import QT_QSS_DIR


class StyleSheet(StyleSheetBase, Enum):
    """Style sheet"""

    DEFUALT = "defualt"
    HWND_LIST_WIDGET = "hwnd_list_widget"
    IMAGE_CARD_WIDGET = "image_card_widget"
    HOME_WIDGET = "home_widget"
    ANNOTATION_WIDGET = "annotation_widget"
    FEATURE_CAPTURE_WIDGET = "feature_capture_widget"

    def path(self, theme=Theme.AUTO):
        theme = qconfig.theme if theme == Theme.AUTO else theme
        return f"{QT_QSS_DIR}/{theme.value.lower()}/{self.value}.qss"
