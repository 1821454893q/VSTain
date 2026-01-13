"""主页组件"""

import os
import threading
from pathlib import Path
import time
from typing import TYPE_CHECKING

import win32gui
from PyQt5.QtCore import Qt, QEasingCurve, QSize, QRectF
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QDialog, QLabel, QFileDialog
from PyQt5.QtGui import QPainter, QPainterPath, QLinearGradient, QColor, QBrush

from gas.util.hwnd_util import get_hwnd_by_class_and_title, WindowInfo, get_window_wh
from gas.util.wrap_util import timeit
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    GroupHeaderCardWidget,
    IconWidget,
    ImageLabel,
    InfoBarIcon,
    MSFluentTitleBar,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SmoothScrollArea,
    isDarkTheme,
    SingleDirectionScrollArea,
    LineEdit,
    InfoBar,
)

from src.vstain.common.settings import RESOURCE_DIR, MODULES_DIR, SCRIPTS_DIR
from src.vstain.utils.platform import is_win11
from src.vstain.widgets.image_card_widget import ImageCardWidget
from src.vstain.widgets.hwnd_list_widget import HwndListWidget
from src.vstain.common.style_sheet import StyleSheet
from src.vstain.common.config import cfg
from src.vstain.utils.logger import get_logger
from gas.ocr_engine import OCREngine, TextAction

from gas.recorder.operation_player import OperationPlayer

log = get_logger()


class HomeWidget(SingleDirectionScrollArea):
    """主页组件"""

    def __init__(self, objectName: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(objectName)

        self._setup_ui()
        self._set_connections()

        self._pause_scripts = True
        self.test_scripts_thread = threading.Thread(target=self.test_script, daemon=True)
        self.test_scripts_thread.start()
        log.debug("测试脚本线程已启动")

        StyleSheet.HOME_WIDGET.apply(self)

    def _setup_ui(self):
        """设置界面 - 直接继承滚动区域版本"""

        # 设置滚动区域属性
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(True)

        # 创建内容窗口
        content_widget = QWidget()
        content_widget.setObjectName("sourceWidget")
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(15)

        # 创建各种组件
        self.set_group_card = GroupHeaderCardWidget()
        self.set_group_card.setTitle("基本设置")
        self.set_group_card.setBorderRadius(8)

        self.find_hwnd_btn = PrimaryPushButton("运行")
        self.find_hwnd_btn.setFixedWidth(100)
        self.set_group_card.addGroup(
            icon=FluentIcon.ERASE_TOOL,
            title="句柄管理",
            content="用于获取句柄.测试截取等功能",
            widget=self.find_hwnd_btn,
        )

        self.capture_btn = PrimaryPushButton("运行")
        self.capture_btn.setFixedWidth(100)
        self.set_group_card.addGroup(
            icon=FluentIcon.ERASE_TOOL,
            title="捕获窗口",
            content="根据下面的窗口标题与类名,捕获窗口",
            widget=self.capture_btn,
        )

        self.hwnd_title_edit = LineEdit()
        self.hwnd_title_edit.setText(cfg.get(cfg.hwndWindowsTitle))
        self.hwnd_title_edit.setFixedWidth(300)
        self.set_group_card.addGroup(
            icon=FluentIcon.FONT, title="窗口标题", content="用于获取句柄的窗口标题", widget=self.hwnd_title_edit
        )

        self.hwnd_classname_edit = LineEdit()
        self.hwnd_classname_edit.setText(cfg.get(cfg.hwndClassname))
        self.hwnd_classname_edit.setFixedWidth(300)
        self.set_group_card.addGroup(
            icon=FluentIcon.DICTIONARY,
            title="窗口类名",
            content="用于获取句柄的窗口类名",
            widget=self.hwnd_classname_edit,
        )

        self.onnx_model_name = ComboBox()
        model_name_list = [str(p.name) for p in Path(MODULES_DIR).iterdir() if p.suffix.lower() in [".onnx"]]
        self.onnx_model_name.addItems(model_name_list)
        if len(model_name_list) == 1:
            cfg.set(cfg.onnxModelName, model_name_list[0])

        self.onnx_model_name.setCurrentText(cfg.get(cfg.onnxModelName))
        self.onnx_model_name.setFixedWidth(300)
        self.set_group_card.addGroup(
            icon=FluentIcon.DICTIONARY,
            title="检测模型",
            content="onnx使用模型选择",
            widget=self.onnx_model_name,
        )

        self.onnx_model_input = ComboBox()
        self.onnx_model_input.addItems(["320", "640", "960", "1280"])
        self.onnx_model_input.setCurrentText(str(cfg.get(cfg.onnxModelInput)))
        self.onnx_model_input.setFixedWidth(300)
        self.set_group_card.addGroup(
            icon=FluentIcon.DICTIONARY,
            title="检测模型",
            content="onnx模型输入限制(需要与模型匹配)",
            widget=self.onnx_model_input,
        )

        self.onnx_provider_combox = ComboBox()
        self.onnx_provider_combox.addItems(["CPUExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"])
        self.onnx_provider_combox.setCurrentText(str(cfg.get(cfg.onnxProvider)))
        self.onnx_provider_combox.setFixedWidth(300)
        self.set_group_card.addGroup(
            icon=FluentIcon.DICTIONARY,
            title="执行器选择",
            content="onnx模型计算处理器选择",
            widget=self.onnx_provider_combox,
        )

        self.run_group_card = GroupHeaderCardWidget()
        self.run_group_card.setTitle("执行脚本")
        self.run_group_card.setBorderRadius(8)

        self.script_name = ComboBox()
        script_name_list = [str(p.name) for p in Path(SCRIPTS_DIR).iterdir() if p.suffix.lower() in [".json"]]
        self.script_name.addItems(script_name_list)
        if len(script_name_list) == 1:
            cfg.set(cfg.scriptName, script_name_list[0])

        self.script_name.setCurrentText(cfg.get(cfg.scriptName))
        self.script_name.setFixedWidth(300)
        self.run_group_card.addGroup(
            icon=FluentIcon.DICTIONARY,
            title="脚本选择",
            content="执行测试脚本选择",
            widget=self.script_name,
        )

        self.run_btn = PrimaryPushButton("开始")
        self.run_btn.setEnabled(False)
        self.run_group_card.addGroup(icon=FluentIcon.ERASE_TOOL, title="脚本1", content="测试开发", widget=self.run_btn)

        self.detail_label = BodyLabel("开发者: jian 邮箱: 不说了")

        # 将组件添加到内容布局
        self.content_layout.addWidget(self.set_group_card)
        self.content_layout.addWidget(self.run_group_card)
        self.content_layout.addStretch(1)
        self.content_layout.addWidget(self.detail_label)

        # 设置内容窗口
        self.setWidget(content_widget)

    def _set_connections(self):
        self.find_hwnd_btn.clicked.connect(self.openHwnd)
        self.hwnd_title_edit.textChanged.connect(lambda: cfg.set(cfg.hwndWindowsTitle, self.hwnd_title_edit.text()))
        self.hwnd_classname_edit.textChanged.connect(
            lambda: cfg.set(cfg.hwndClassname, self.hwnd_classname_edit.text())
        )
        self.capture_btn.clicked.connect(self._capture)
        self.onnx_model_name.currentTextChanged.connect(lambda: cfg.set(cfg.onnxModelName, self.onnx_model_name.text()))
        self.onnx_model_input.currentTextChanged.connect(
            lambda: cfg.set(cfg.onnxModelInput, int(self.onnx_model_input.text()))
        )
        self.onnx_provider_combox.currentTextChanged.connect(
            lambda: cfg.set(cfg.onnxProvider, self.onnx_provider_combox.text())
        )
        self.script_name.currentTextChanged.connect(lambda: cfg.set(cfg.scriptName, self.script_name.text()))
        self.run_btn.clicked.connect(self.run_script)

    def udpate_cfg(self):
        self.hwnd_classname_edit.setText(cfg.get(cfg.hwndClassname))
        self.hwnd_title_edit.setText(cfg.get(cfg.hwndWindowsTitle))

    def openHwnd(self):
        widget = HwndListWidget()
        widget.show()
        widget.cfgUpdated.connect(self.udpate_cfg)

    def _capture(self):
        hwnd_list = get_hwnd_by_class_and_title(
            class_name=cfg.get(cfg.hwndClassname),
            titles=cfg.get(cfg.hwndWindowsTitle),
        )
        if hwnd_list is None or len(hwnd_list) == 0:
            InfoBar.warning(title="警告", content="未能找到对应窗口句柄", parent=self, duration=3000)
            return

        hwnd = hwnd_list[0]
        win = WindowInfo(
            hwnd=hwnd,
            size=get_window_wh(hwnd),
            title=win32gui.GetWindowText(hwnd),
            class_name=win32gui.GetClassName(hwnd),
            position=[0, 0],
        )
        widget = ImageCardWidget(windows=win)
        widget.show()

    def run_script(self):
        if self._pause_scripts:
            self.run_btn.setText("暂停")
            log.debug(f"operation player init. scirpt nmae:{cfg.get(cfg.scriptName)}")
            self.player = OperationPlayer(self.engine.device)
            self.player.load_from_file(str(SCRIPTS_DIR / cfg.get(cfg.scriptName)))
            self._pause_scripts = False
        else:
            self.run_btn.setText("开始")
            self._pause_scripts = True

    def test_script(self):
        log.debug("ocr engine init")
        self.engine = OCREngine.create_with_window(cfg.get(cfg.hwndWindowsTitle), cfg.get(cfg.hwndClassname), 2, False)
        log.debug(f"ocr engine init done")
        self.flag = False
        self.run_btn.setEnabled(True)

        while True:
            if self._pause_scripts:
                time.sleep(2)
                continue
            self.run()
            time.sleep(2)

    def qili(self, x, y, t, o: OCREngine):
        if not self.flag:
            return
        self.flag = False
        log.debug(f"开始执行脚本: {cfg.get(cfg.scriptName)}")
        self.player.replay()

    def kaishi(self, x, y, t, o: OCREngine):
        o.click(x, y)
        self.flag = True

    def run(self):
        action = [
            TextAction("再次进行", lambda x, y, t, o: o.click(x, y)),
            TextAction("开始挑战", self.kaishi),
            TextAction("驱离所有敌人", self.qili),
            TextAction("避险", self.qili),
        ]
        self.engine.process_texts(action)
