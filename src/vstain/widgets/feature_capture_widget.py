"""窗口特征捕获和匹配工具"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint, QRect
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QFileDialog,
)

from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    DoubleSpinBox,
    SpinBox,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
    ExpandGroupSettingCard,
    ImageLabel,
    CheckBox,
    TextEdit,
    ListWidget,
    SingleDirectionScrollArea,
)

from gas.util.hwnd_util import get_hwnd_by_class_and_title
from gas.util.screenshot_util import screenshot
from gas.util.img_util import bgr2rgb
from src.vstain.common.style_sheet import StyleSheet
from src.vstain.common.config import cfg
from src.vstain.common.settings import RESOURCE_DIR
from src.vstain.utils.logger import get_logger

log = get_logger()


@dataclass
class WindowConfig:
    """窗口配置"""

    class_name: str
    titles: List[str]
    description: str = ""


@dataclass
class FeatureTemplate:
    """特征模板"""

    name: str
    hwnd: int
    position: Dict[str, int]  # x, y, width, height
    confidence_threshold: float = 0.8
    keypoints: Optional[List] = None
    descriptors: Optional[np.ndarray] = None

    def to_dict(self):
        """转换为字典，只保存匹配必需的数据"""
        import base64
        import zlib

        data = {
            "name": self.name,
            "hwnd": self.hwnd,
            "position": self.position,
            "confidence_threshold": self.confidence_threshold,
        }

        # 只保存描述符（匹配必需）
        if self.descriptors is not None:
            compressed_descriptors = zlib.compress(self.descriptors.tobytes())
            data["descriptors"] = base64.b64encode(compressed_descriptors).decode("ascii")
            data["descriptors_shape"] = self.descriptors.shape

        # 只保存关键点基本信息（匹配必需）
        if self.keypoints:
            data["keypoints_info"] = self._keypoints_to_compact_list()

        return data

    def _keypoints_to_compact_list(self):
        """将关键点转换为紧凑格式"""
        if not self.keypoints:
            return None

        keypoints_info = []
        for kp in self.keypoints:
            # 只保存位置和尺寸（匹配时有用）
            keypoint_data = [
                float(kp.pt[0]),  # x
                float(kp.pt[1]),  # y
                float(kp.size),  # size
                float(kp.angle),  # angle
            ]
            keypoints_info.append(keypoint_data)
        return keypoints_info

    @classmethod
    def from_dict(cls, data):
        """从字典创建对象"""
        import base64
        import zlib

        # 解压缩描述符数据（匹配必需）
        descriptors = None
        if "descriptors" in data and data["descriptors"]:
            try:
                compressed_descriptors = base64.b64decode(data["descriptors"])
                decompressed_descriptors = zlib.decompress(compressed_descriptors)
                descriptors = np.frombuffer(decompressed_descriptors, dtype=np.uint8)
                if "descriptors_shape" in data:
                    descriptors = descriptors.reshape(data["descriptors_shape"])
            except Exception as e:
                log.error(f"描述符解码失败: {e}")
                return None

        # 重建关键点对象（匹配必需）
        keypoints = None
        if data.get("keypoints_info"):
            keypoints = cls._compact_list_to_keypoints(data["keypoints_info"])

        return cls(
            name=data["name"],
            hwnd=data["hwnd"],
            position=data["position"],
            confidence_threshold=data.get("confidence_threshold", 0.8),
            keypoints=keypoints,
            descriptors=descriptors,
        )

    @staticmethod
    def _compact_list_to_keypoints(keypoints_info):
        """从紧凑格式重建关键点"""
        if not keypoints_info:
            return None

        keypoints = []
        for kp_info in keypoints_info:
            kp = cv2.KeyPoint()
            kp.pt = (kp_info[0], kp_info[1])  # x, y
            kp.size = kp_info[2]  # size
            kp.angle = kp_info[3]  # angle
            kp.response = 0.01  # 默认响应值
            kp.octave = 0
            kp.class_id = -1
            keypoints.append(kp)

        return keypoints


class RegionSelectionLabel(ImageLabel):
    """支持区域选择的图像标签"""

    regionSelected = pyqtSignal(dict)  # 发送区域信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selection_start = None
        self.selection_end = None
        self.is_selecting = False
        self.selected_region = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selection_start = event.pos()
            self.selection_end = event.pos()
            self.is_selecting = True

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.selection_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.selection_end = event.pos()
            self.is_selecting = False

            # 计算选择的区域
            start_x = min(self.selection_start.x(), self.selection_end.x())
            start_y = min(self.selection_start.y(), self.selection_end.y())
            end_x = max(self.selection_start.x(), self.selection_end.x())
            end_y = max(self.selection_start.y(), self.selection_end.y())

            start_x = max(0, start_x)
            start_y = max(0, start_y)

            width = end_x - start_x
            height = end_y - start_y

            if width > 10 and height > 10:  # 最小区域大小
                self.selected_region = {"x": start_x, "y": start_y, "width": width, "height": height}
                self.regionSelected.emit(self.selected_region)

            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.is_selecting and self.selection_start and self.selection_end:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.SolidLine))

            start_x = min(self.selection_start.x(), self.selection_end.x())
            start_y = min(self.selection_start.y(), self.selection_end.y())
            end_x = max(self.selection_start.x(), self.selection_end.x())
            end_y = max(self.selection_start.y(), self.selection_end.y())

            painter.drawRect(start_x, start_y, end_x - start_x, end_y - start_y)

        elif self.selected_region:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(0, 255, 0), 2, Qt.SolidLine))
            painter.drawRect(
                self.selected_region["x"],
                self.selected_region["y"],
                self.selected_region["width"],
                self.selected_region["height"],
            )

    def clear_selection(self):
        """清除选择区域"""
        self.selected_region = None
        self.selection_start = None
        self.selection_end = None
        self.update()


# 在类定义之前添加ORB配置类
@dataclass
class ORBConfig:
    """ORB算法配置"""

    name: str
    description: str
    nfeatures: int
    scaleFactor: float
    nlevels: int
    edgeThreshold: int
    patchSize: int
    fastThreshold: int
    scoreType: int = cv2.ORB_HARRIS_SCORE
    WTA_K: int = 2
    firstLevel: int = 0


class WindowFeatureCaptureWidget(QWidget):
    """窗口特征捕获和匹配工具"""

    # 信号 - 使用兼容的类型
    templateCaptured = pyqtSignal(object)  # FeatureTemplate 对象
    matchFound = pyqtSignal(str, object, float)  # 模板名, 位置字典, 置信度

    def __init__(self, objectName: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(objectName)

        # ORB配置预设
        self.orb_configs = self._get_orb_configs()
        self.current_orb_config = self.orb_configs[0]  # 默认使用第一个配置

        # 窗口配置
        self.window_configs = self._load_window_configs()
        self.current_hwnd = None
        self.current_window_image = None
        self.feature_templates = {}  # Dict[str, FeatureTemplate]
        self.current_match_results = []  # 存储当前匹配结果

        # 匹配器
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.orb = self._create_orb_detector()

        self._setup_ui()
        self._set_connections()

        StyleSheet.FEATURE_CAPTURE_WIDGET.apply(self)

    def _setup_ui(self):
        """设置界面"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 先创建所有部件
        self._create_left_side_widgets()
        self._create_right_side_widgets()

        # 设置布局
        self._setup_left_side_layout()
        self._setup_right_side_layout()
        self._setup_main_layout(main_layout)

        # 设置定时器
        self._setup_timers()

    def _create_left_side_widgets(self):
        """创建左侧所有部件"""
        # 窗口选择组部件
        self.config_combo = ComboBox()
        self.refresh_btn = PushButton("刷新窗口")
        self.connect_btn = PrimaryPushButton("连接窗口")
        self.window_list = ListWidget()
        self.window_status_label = CaptionLabel("未连接任何窗口")

        # ORB配置组部件
        self.orb_config_combo = ComboBox()
        self.orb_config_details = CaptionLabel("")
        self.custom_orb_btn = PushButton("自定义参数")

        # 特征模板管理组部件
        self.template_name_edit = LineEdit()
        self.template_name_edit.setPlaceholderText("输入模板名称")
        self.clear_region_btn = PushButton("清除区域")
        self.capture_full_btn = PushButton("全屏捕获")
        self.capture_btn = PrimaryPushButton("捕获特征区域")
        self.template_list = ListWidget()
        self.delete_template_btn = PushButton("删除模板")
        self.export_templates_btn = PushButton("导出模板")
        self.import_templates_btn = PushButton("导入模板")

        # 匹配设置组部件
        self.threshold_spin = DoubleSpinBox()
        self.threshold_spin.setRange(0.1, 1.0)
        self.threshold_spin.setValue(0.7)
        self.threshold_spin.setSingleStep(0.05)
        self.match_interval_spin = SpinBox()
        self.match_interval_spin.setRange(100, 5000)
        self.match_interval_spin.setValue(1000)
        self.match_interval_spin.setSuffix(" ms")
        self.start_match_btn = PrimaryPushButton("开始匹配")

    def _create_right_side_widgets(self):
        """创建右侧所有部件"""
        self.preview_label = RegionSelectionLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(400, 300)
        self.preview_label.setStyleSheet("border: 1px solid gray; background-color: #1a1a1a;")
        self.preview_label.setText("窗口预览区域\n\n拖动鼠标选择区域")

        self.refresh_preview_btn = PushButton("刷新预览")
        self.auto_preview_check = CheckBox("自动刷新预览")
        self.auto_preview_check.setChecked(False)

        self.result_text = TextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(200)

        self.match_progress = QProgressBar()
        self.match_progress.setVisible(False)

    def _setup_left_side_layout(self):
        """设置左侧布局"""
        # 创建滚动区域
        self.left_scroll = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical)
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 创建内容widget
        left_content_widget = QWidget()
        self.left_layout = QVBoxLayout(left_content_widget)
        self.left_layout.setContentsMargins(5, 5, 15, 5)
        self.left_layout.setSpacing(10)

        # 窗口选择组
        window_group = QGroupBox("窗口选择")
        window_layout = QVBoxLayout(window_group)

        # 窗口配置选择
        config_layout = QHBoxLayout()
        config_layout.addWidget(BodyLabel("窗口配置:"))

        # 填充窗口配置
        for config in self.window_configs:
            self.config_combo.addItem(config.description, userData=config)
        config_layout.addWidget(self.config_combo)
        window_layout.addLayout(config_layout)

        # 刷新和连接按钮
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.connect_btn)
        window_layout.addLayout(button_layout)

        # 窗口列表
        self.window_list.setMaximumHeight(150)
        window_layout.addWidget(self.window_list)
        window_layout.addWidget(self.window_status_label)

        self.left_layout.addWidget(window_group)

        # ORB配置组
        orb_group = QGroupBox("特征检测配置")
        orb_layout = QVBoxLayout(orb_group)

        # ORB配置选择
        orb_config_layout = QHBoxLayout()
        orb_config_layout.addWidget(BodyLabel("检测配置:"))

        # 填充ORB配置
        for config in self.orb_configs:
            self.orb_config_combo.addItem(config.description, userData=config)
        orb_config_layout.addWidget(self.orb_config_combo)
        orb_layout.addLayout(orb_config_layout)

        # 配置详情显示
        self._update_orb_config_details()
        orb_layout.addWidget(self.orb_config_details)
        orb_layout.addWidget(self.custom_orb_btn)

        self.left_layout.addWidget(orb_group)

        # 特征模板管理组
        template_group = QGroupBox("特征模板管理")
        template_layout = QVBoxLayout(template_group)

        # 模板名称输入
        name_layout = QHBoxLayout()
        name_layout.addWidget(BodyLabel("模板名称:"))
        name_layout.addWidget(self.template_name_edit)
        template_layout.addLayout(name_layout)

        # 区域选择控制
        region_layout = QHBoxLayout()
        region_layout.addWidget(self.clear_region_btn)
        region_layout.addWidget(self.capture_full_btn)
        template_layout.addLayout(region_layout)

        # 捕获按钮
        self.capture_btn.setEnabled(False)
        template_layout.addWidget(self.capture_btn)

        # 模板列表
        self.template_list.setMinimumHeight(200)
        template_layout.addWidget(self.template_list)

        # 模板操作按钮
        template_btn_layout = QHBoxLayout()
        template_btn_layout.addWidget(self.delete_template_btn)
        template_btn_layout.addWidget(self.export_templates_btn)
        template_btn_layout.addWidget(self.import_templates_btn)
        template_layout.addLayout(template_btn_layout)

        self.left_layout.addWidget(template_group)

        # 匹配设置组
        match_group = QGroupBox("匹配设置")
        match_layout = QVBoxLayout(match_group)

        # 匹配阈值
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(BodyLabel("匹配阈值:"))
        threshold_layout.addWidget(self.threshold_spin)
        match_layout.addLayout(threshold_layout)

        # 自动匹配
        auto_layout = QHBoxLayout()
        auto_layout.addWidget(BodyLabel("匹配间隔:"))
        auto_layout.addWidget(self.match_interval_spin)
        match_layout.addLayout(auto_layout)

        # 开始匹配按钮
        match_layout.addWidget(self.start_match_btn)

        self.left_layout.addWidget(match_group)
        self.left_layout.addStretch(1)

        # 设置内容widget到滚动区域
        self.left_scroll.setWidget(left_content_widget)
        self.left_scroll.setFixedWidth(380)
        self.left_scroll.enableTransparentBackground()

    def _setup_right_side_layout(self):
        """设置右侧布局"""
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)

        # 窗口预览组
        preview_group = QGroupBox("窗口预览")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.addWidget(self.preview_label)

        # 预览控制
        preview_control_layout = QHBoxLayout()
        preview_control_layout.addWidget(self.refresh_preview_btn)
        preview_control_layout.addStretch()
        preview_control_layout.addWidget(self.auto_preview_check)
        preview_layout.addLayout(preview_control_layout)

        right_layout.addWidget(preview_group)

        # 匹配结果组
        result_group = QGroupBox("匹配结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.addWidget(self.result_text)
        result_layout.addWidget(self.match_progress)

        right_layout.addWidget(result_group)

    def _setup_main_layout(self, main_layout):
        """设置主布局"""
        main_layout.addWidget(self.left_scroll)
        main_layout.addWidget(self.right_widget)

        # 设置布局比例
        main_layout.setStretchFactor(self.left_scroll, 1)
        main_layout.setStretchFactor(self.right_widget, 2)

    def _setup_timers(self):
        """设置定时器"""
        # 自动刷新定时器
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_window_list)
        self.refresh_timer.start(2000)

        # 自动预览定时器
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self._update_preview)

        # 自动匹配定时器
        self.auto_match_timer = QTimer()
        self.auto_match_timer.timeout.connect(self._auto_match_templates)

    def _set_connections(self):
        """设置信号连接"""
        # 按钮连接
        self.refresh_btn.clicked.connect(self._refresh_window_list)
        self.connect_btn.clicked.connect(self._connect_to_window)
        self.capture_btn.clicked.connect(self._capture_feature_template)
        self.refresh_preview_btn.clicked.connect(self._update_preview)
        self.start_match_btn.clicked.connect(self._toggle_auto_match)
        self.clear_region_btn.clicked.connect(self._clear_region_selection)
        self.capture_full_btn.clicked.connect(self._capture_full_screen)
        self.custom_orb_btn.clicked.connect(self._show_custom_orb_dialog)

        # 列表连接
        self.window_list.itemClicked.connect(self._on_window_selected)
        self.template_list.itemClicked.connect(self._on_template_selected)

        # 组合框连接
        self.orb_config_combo.currentIndexChanged.connect(self._on_orb_config_changed)

        # 删除模板按钮
        self.delete_template_btn.clicked.connect(self._delete_template)
        self.export_templates_btn.clicked.connect(self._export_templates)
        self.import_templates_btn.clicked.connect(self._import_templates)

        # 复选框连接
        self.auto_preview_check.toggled.connect(self._toggle_auto_preview)

        # 微调框信号
        self.match_interval_spin.valueChanged.connect(lambda v: self.auto_match_timer.setInterval(v))

        # 区域选择信号
        self.preview_label.regionSelected.connect(self._on_region_selected)

    def _get_orb_configs(self):
        """获取ORB配置预设"""
        return [
            ORBConfig(
                name="small_icons",
                description="小图标优化 (25x25-50x50)",
                nfeatures=50,
                scaleFactor=1.1,
                nlevels=3,
                edgeThreshold=5,
                patchSize=15,
                fastThreshold=5,
                scoreType=cv2.ORB_FAST_SCORE,
            ),
            ORBConfig(
                name="medium_ui",
                description="中等UI元素 (50x50-100x100)",
                nfeatures=200,
                scaleFactor=1.15,
                nlevels=5,
                edgeThreshold=15,
                patchSize=20,
                fastThreshold=10,
            ),
            ORBConfig(
                name="large_areas",
                description="大区域匹配 (100x100+)",
                nfeatures=1000,
                scaleFactor=1.2,
                nlevels=8,
                edgeThreshold=31,
                patchSize=31,
                fastThreshold=20,
            ),
            ORBConfig(
                name="high_precision",
                description="高精度匹配",
                nfeatures=2000,
                scaleFactor=1.1,
                nlevels=10,
                edgeThreshold=15,
                patchSize=31,
                fastThreshold=15,
            ),
            ORBConfig(
                name="fast_matching",
                description="快速匹配",
                nfeatures=300,
                scaleFactor=1.3,
                nlevels=4,
                edgeThreshold=20,
                patchSize=20,
                fastThreshold=25,
            ),
            ORBConfig(
                name="text_rich",
                description="文字丰富区域",
                nfeatures=500,
                scaleFactor=1.15,
                nlevels=6,
                edgeThreshold=10,
                patchSize=25,
                fastThreshold=8,
            ),
        ]

    def _create_orb_detector(self):
        """根据当前配置创建ORB检测器"""
        config = self.current_orb_config
        return cv2.ORB_create(
            nfeatures=config.nfeatures,
            scaleFactor=config.scaleFactor,
            nlevels=config.nlevels,
            edgeThreshold=config.edgeThreshold,
            firstLevel=config.firstLevel,
            WTA_K=config.WTA_K,
            scoreType=config.scoreType,
            patchSize=config.patchSize,
            fastThreshold=config.fastThreshold,
        )

    def _load_window_configs(self):
        """加载窗口配置"""
        return [
            WindowConfig(
                class_name=cfg.get(cfg.hwndClassname),
                titles=[cfg.get(cfg.hwndWindowsTitle)],
                description="缓存配置窗口",
            ),
            WindowConfig(class_name="UnityWndClass", titles=["原神", "Genshin Impact"], description="原神游戏窗口"),
        ]

    def _show_custom_orb_dialog(self):
        """显示自定义ORB参数对话框"""
        from qfluentwidgets import Dialog, SpinBox, DoubleSpinBox, MessageBox

        dialog = Dialog("自定义ORB参数", self)

        v_layout = QVBoxLayout()

        # 特征点数量
        nfeatures_layout = QHBoxLayout()
        nfeatures_layout.addWidget(BodyLabel("特征点数量:"))
        nfeatures_spin = SpinBox()
        nfeatures_spin.setRange(10, 5000)
        nfeatures_spin.setValue(self.current_orb_config.nfeatures)
        nfeatures_layout.addWidget(nfeatures_spin)
        v_layout.addLayout(nfeatures_layout)

        # 缩放因子
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(BodyLabel("缩放因子:"))
        scale_spin = DoubleSpinBox()
        scale_spin.setRange(1.05, 2.0)
        scale_spin.setSingleStep(0.05)
        scale_spin.setValue(self.current_orb_config.scaleFactor)
        scale_layout.addWidget(scale_spin)
        v_layout.addLayout(scale_layout)

        # 金字塔层数
        levels_layout = QHBoxLayout()
        levels_layout.addWidget(BodyLabel("金字塔层数:"))
        levels_spin = SpinBox()
        levels_spin.setRange(1, 20)
        levels_spin.setValue(self.current_orb_config.nlevels)
        levels_layout.addWidget(levels_spin)
        v_layout.addLayout(levels_layout)

        # Patch大小
        patch_layout = QHBoxLayout()
        patch_layout.addWidget(BodyLabel("Patch大小:"))
        patch_spin = SpinBox()
        patch_spin.setRange(5, 50)
        patch_spin.setValue(self.current_orb_config.patchSize)
        patch_layout.addWidget(patch_spin)
        v_layout.addLayout(patch_layout)

        # FAST阈值
        fast_layout = QHBoxLayout()
        fast_layout.addWidget(BodyLabel("FAST阈值:"))
        fast_spin = SpinBox()
        fast_spin.setRange(1, 50)
        fast_spin.setValue(self.current_orb_config.fastThreshold)
        fast_layout.addWidget(fast_spin)
        v_layout.addLayout(fast_layout)

        dialog.addLayout(v_layout)

        def on_confirm():
            custom_config = ORBConfig(
                name="custom",
                description="自定义配置",
                nfeatures=nfeatures_spin.value(),
                scaleFactor=scale_spin.value(),
                nlevels=levels_spin.value(),
                edgeThreshold=15,  # 固定值，通常与patchSize相关
                patchSize=patch_spin.value(),
                fastThreshold=fast_spin.value(),
            )

            # 添加到配置列表
            self.orb_configs.append(custom_config)
            self.orb_config_combo.addItem(custom_config.description, userData=custom_config)
            self.orb_config_combo.setCurrentIndex(self.orb_config_combo.count() - 1)

            dialog.close()

        dialog.yesSignal.connect(on_confirm)
        dialog.exec()

    def _update_orb_config_details(self):
        """更新ORB配置详情显示"""
        config = self.orb_config_combo.currentData()
        if config:
            details = (
                f"特征点: {config.nfeatures} | "
                f"金字塔: {config.nlevels}层 | "
                f"缩放: {config.scaleFactor} | "
                f"Patch: {config.patchSize} | "
                f"阈值: {config.fastThreshold}"
            )
            self.orb_config_details.setText(details)

    def _on_orb_config_changed(self):
        """ORB配置变化"""
        self.current_orb_config = self.orb_config_combo.currentData()
        self.orb = self._create_orb_detector()
        self._update_orb_config_details()

        # 显示配置提示
        config = self.current_orb_config
        if config.name == "small_icons":
            tip = "适用于25x25-50x50像素的小图标"
        elif config.name == "medium_ui":
            tip = "适用于50x50-100x100像素的UI元素"
        elif config.name == "large_areas":
            tip = "适用于100x100像素以上的大区域"
        elif config.name == "high_precision":
            tip = "精度优先，速度较慢"
        elif config.name == "fast_matching":
            tip = "速度优先，精度较低"
        elif config.name == "text_rich":
            tip = "适用于文字丰富的区域"
        else:
            tip = "自定义配置"

        InfoBar.info(title="配置已更新", content=tip, parent=self, duration=1500)

    def _refresh_window_list(self):
        """刷新窗口列表"""
        self.window_list.clear()

        current_config = self.config_combo.currentData()
        if not current_config:
            return

        # 获取匹配的窗口
        hwnds = get_hwnd_by_class_and_title(current_config.class_name, current_config.titles)

        for hwnd in hwnds:
            # 获取窗口标题
            try:
                import win32gui

                title = win32gui.GetWindowText(hwnd)
                item_text = f"{title} (0x{hwnd:X})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, hwnd)
                self.window_list.addItem(item)
            except Exception as e:
                log.error(f"获取窗口信息失败: {e}")

    def _on_window_selected(self, item):
        """窗口选择变化"""
        hwnd = item.data(Qt.ItemDataRole.UserRole)
        self.current_hwnd = hwnd
        self.window_status_label.setText(f"已选择窗口: 0x{hwnd:X}")
        self.capture_btn.setEnabled(True)
        self._update_preview()

    def _connect_to_window(self):
        """连接到选中的窗口"""
        if self.window_list.currentItem():
            self._on_window_selected(self.window_list.currentItem())
        else:
            InfoBar.warning(title="警告", content="请先选择一个窗口", parent=self)

    def _update_preview(self):
        """更新窗口预览"""
        if not self.current_hwnd:
            return

        try:
            # 捕获窗口图像
            screenshot_img = screenshot(self.current_hwnd)
            if screenshot_img is not None:
                self.current_window_image = screenshot_img.copy()

                # 转换为 QImage 并显示
                height, width, channel = screenshot_img.shape
                bytes_per_line = 3 * width

                q_img = QImage(bgr2rgb(screenshot_img).data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

                # 缩放以适应预览区域
                scaled_pixmap = QPixmap.fromImage(q_img).scaled(
                    self.preview_label.width(),
                    self.preview_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_label.setPixmap(scaled_pixmap)

        except Exception as e:
            log.error(f"更新预览失败: {e}")

    def _toggle_auto_preview(self, checked):
        """切换自动预览"""
        if checked and self.current_hwnd:
            self.preview_timer.start(500)  # 0.5秒刷新一次
        else:
            self.preview_timer.stop()

    def _on_region_selected(self, region):
        """区域选择完成"""
        self.selected_region = region
        InfoBar.info(title="提示", content=f"已选择区域: {region['width']}x{region['height']}", parent=self)

    def _clear_region_selection(self):
        """清除区域选择"""
        self.preview_label.clear_selection()
        self.selected_region = None

    def _capture_full_screen(self):
        """捕获全屏"""
        self.selected_region = None
        self.preview_label.clear_selection()
        InfoBar.info(title="提示", content="已选择全屏捕获", parent=self)

    def _capture_feature_template(self):
        """捕获特征模板"""
        if self.current_window_image is None or not self.template_name_edit.text():
            InfoBar.warning(title="警告", content="请先连接窗口并输入模板名称", parent=self)
            return

        template_name = self.template_name_edit.text().strip()
        if template_name in self.feature_templates:
            InfoBar.warning(title="警告", content="模板名称已存在", parent=self)
            return

        # 获取选择的区域或使用全屏
        if hasattr(self, "selected_region") and self.selected_region:
            # 计算实际图像坐标（考虑缩放）
            scale_x = self.current_window_image.shape[1] / self.preview_label.pixmap().width()
            scale_y = self.current_window_image.shape[0] / self.preview_label.pixmap().height()

            x = int(self.selected_region["x"] * scale_x)
            y = int(self.selected_region["y"] * scale_y)
            width = int(self.selected_region["width"] * scale_x)
            height = int(self.selected_region["height"] * scale_y)

            # 截取区域
            template_image = self.current_window_image[y : y + height, x : x + width]
            position = {"x": x, "y": y, "width": width, "height": height}
            log.debug(f"截图特征 position {position}, 图像尺寸: {template_image.shape}")
        else:
            # 使用全屏
            template_image = self.current_window_image.copy()
            position = {
                "x": 0,
                "y": 0,
                "width": self.current_window_image.shape[1],
                "height": self.current_window_image.shape[0],
            }

        # 对小图标进行预处理优化
        if width <= 60 and height <= 60:
            template_image = self._preprocess_small_icon(template_image)

        # 提取特征
        keypoints, descriptors = self.orb.detectAndCompute(template_image, None)

        # 调试信息
        log.debug(
            f"提取特征结果: 关键点={len(keypoints) if keypoints else 0}, 描述符形状={descriptors.shape if descriptors is not None else 'None'}"
        )

        if descriptors is not None and len(descriptors) > 0:
            # 创建模板（不保存image）
            template = FeatureTemplate(
                name=template_name,
                hwnd=self.current_hwnd,
                position=position,
                confidence_threshold=self.threshold_spin.value(),
                keypoints=keypoints,
                descriptors=descriptors,
            )

            self.feature_templates[template_name] = template
            self.template_list.addItem(template_name)
            self.template_name_edit.clear()
            self._clear_region_selection()

            InfoBar.success(
                title="成功", content=f"已捕获模板: {template_name} ({len(keypoints)}个特征点)", parent=self
            )
            self.templateCaptured.emit(template)
        else:
            # 提供详细错误信息
            error_msg = self._get_feature_extraction_error(template_image, keypoints)
            InfoBar.error(title="错误", content=error_msg, parent=self)

    def _preprocess_small_icon(self, image):
        """小图标预处理"""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 使用CLAHE增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)

        return gray

    def _get_feature_extraction_error(self, image, keypoints):
        """获取特征提取错误信息"""
        if len(keypoints) == 0:
            return "未检测到任何特征点，建议：\n1. 选择对比度更高的区域\n2. 尝试不同的检测配置\n3. 扩大选择区域"
        else:
            return f"检测到 {len(keypoints)} 个特征点但无法生成描述符\n建议尝试'小图标优化'配置"

    def _on_template_selected(self, item):
        """模板选择变化"""
        template_name = item.text()
        if template_name in self.feature_templates:
            template = self.feature_templates[template_name]
            # 可以在这里显示模板详情
            self.result_text.setText(
                f"模板: {template_name}\n"
                f"位置: {template.position}\n"
                f"尺寸: {template.position["width"]}x{template.position["height"]}\n"
                f"阈值: {template.confidence_threshold}"
            )

    def _delete_template(self):
        """删除选中的模板"""
        current_item = self.template_list.currentItem()
        if current_item:
            template_name = current_item.text()
            del self.feature_templates[template_name]
            self.template_list.takeItem(self.template_list.row(current_item))
            InfoBar.success(title="成功", content=f"已删除模板: {template_name}", parent=self)

    def _toggle_auto_match(self):
        """切换自动匹配"""
        if self.auto_match_timer.isActive():
            self.auto_match_timer.stop()
            self.start_match_btn.setText("开始匹配")
            self.match_progress.setVisible(False)
        else:
            interval = self.match_interval_spin.value()
            self.auto_match_timer.start(interval)
            self.start_match_btn.setText("停止匹配")
            self.match_progress.setVisible(True)

    def _auto_match_templates(self):
        """自动匹配模板"""
        if not self.current_hwnd or not self.feature_templates:
            return

        # 捕获当前窗口图像
        current_image = screenshot(self.current_hwnd)
        if current_image is None:
            return

        self.current_match_results = []

        for template_name, template in self.feature_templates.items():
            # 直接使用保存的描述符进行匹配
            des1 = template.descriptors
            try:
                # 检查模板描述符是否有效
                if des1 is None or not hasattr(des1, "shape") or len(des1.shape) < 2 or des1.shape[0] == 0:
                    continue

                kp2, des2 = self.orb.detectAndCompute(current_image, None)

                # 检查当前图像描述符是否有效
                if des2 is None or not hasattr(des2, "shape") or len(des2.shape) < 2 or des2.shape[0] == 0:
                    continue

                # 确保两个描述符都有足够的特征点
                if des1.shape[0] > 0 and des2.shape[0] > 0:
                    try:
                        matches = self.matcher.match(des1, des2)
                        matches = sorted(matches, key=lambda x: x.distance)

                        # 计算匹配度
                        if len(matches) > 10:
                            good_matches = [m for m in matches if m.distance < 50]
                            confidence = len(good_matches) / len(matches)

                            if confidence >= template.confidence_threshold:
                                result = {
                                    "template": template_name,
                                    "confidence": confidence,
                                    "matches": len(good_matches),
                                    "position": template.position,
                                    "keypoints": kp2,
                                }
                                self.current_match_results.append(result)
                    except Exception as match_e:
                        log.debug(f"模板 {template_name} 匹配失败: {match_e}")
                        continue
            except Exception as e:
                log.error(e)
                return

            # 显示结果并更新预览
            self._display_match_results(self.current_match_results)
            self._update_preview_with_matches()

    def _display_match_results(self, results):
        """显示匹配结果"""
        if not results:
            self.result_text.setText("未找到匹配的模板")
            return

        result_text = "匹配结果:\n"
        for result in sorted(results, key=lambda x: x["confidence"], reverse=True):
            result_text += (
                f"✅ {result['template']}: 置信度 {result['confidence']:.3f} ({result['matches']} 个匹配点)\n"
            )

        self.result_text.setText(result_text)

    def _update_preview_with_matches(self):
        """更新预览图像并标记匹配点"""
        if self.current_window_image is None or self.current_match_results is None:
            return

        try:
            # 创建副本用于绘制
            display_image = self.current_window_image.copy()

            # 绘制匹配结果
            for result in self.current_match_results:
                # 绘制匹配区域
                pos = result["position"]
                cv2.rectangle(
                    display_image,
                    (pos["x"], pos["y"]),
                    (pos["x"] + pos["width"], pos["y"] + pos["height"]),
                    (0, 255, 0),
                    2,
                )

                # 绘制关键点
                if "keypoints" in result and result["keypoints"]:
                    for kp in result["keypoints"][:20]:  # 只绘制前20个关键点
                        x, y = int(kp.pt[0]), int(kp.pt[1])
                        cv2.circle(display_image, (x, y), 3, (255, 0, 0), -1)

                # 添加文本标签
                label = f"{result['template']} ({result['confidence']:.2f})"
                cv2.putText(
                    display_image, label, (pos["x"], pos["y"] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1
                )

            # 更新预览
            height, width, channel = display_image.shape
            bytes_per_line = 3 * width
            q_img = QImage(bgr2rgb(display_image).data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

            scaled_pixmap = QPixmap.fromImage(q_img).scaled(
                self.preview_label.width(),
                self.preview_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled_pixmap)

        except Exception as e:
            log.error(f"更新匹配预览失败: {e}")

    def _export_templates(self):
        """导出模板"""
        if not self.feature_templates:
            InfoBar.warning(title="提示", content="没有模板可导出", parent=self)
            return

        try:

            # 获取窗口标题作为默认文件名
            window_title = "templates"
            if self.current_hwnd:
                import win32gui

                window_title = win32gui.GetWindowText(self.current_hwnd)
                # 清理文件名中的非法字符
                window_title = "".join(c for c in window_title if c.isalnum() or c in (" ", "-", "_")).rstrip()
                if not window_title:
                    window_title = "templates"

            # 默认路径
            default_dir = Path(RESOURCE_DIR) / "features" / window_title
            file_path, _ = QFileDialog.getSaveFileName(
                self, "导出模板", str(default_dir / f"{window_title}.json"), "JSON Files (*.json)"
            )

            if file_path:
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                # 准备导出数据
                export_data = {}
                for name, template in self.feature_templates.items():
                    export_data[name] = template.to_dict()

                # 保存到文件
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)

                InfoBar.success(title="成功", content=f"已导出 {len(export_data)} 个模板到 {file_path}", parent=self)

        except Exception as e:
            log.error(f"导出模板失败: {e}")
            InfoBar.error(title="错误", content=f"导入失败: {str(e)}", parent=self)

    def _import_templates(self):
        """导入模板"""
        try:
            default_dir = Path(RESOURCE_DIR) / "features"
            default_dir.mkdir(parents=True, exist_ok=True)

            file_path, _ = QFileDialog.getOpenFileName(self, "导入模板", str(default_dir), "JSON Files (*.json)")

            if file_path:
                with open(file_path, "r", encoding="utf-8") as f:
                    import_data = json.load(f)

                imported_count = 0
                for name, template_data in import_data.items():
                    try:
                        template = FeatureTemplate.from_dict(template_data)
                        if template is not None:  # 检查模板是否成功创建
                            self.feature_templates[name] = template
                            # 更新列表
                            if name not in [
                                self.template_list.item(i).text() for i in range(self.template_list.count())
                            ]:
                                self.template_list.addItem(name)
                            imported_count += 1
                        else:
                            log.error(f"模板 {name} 创建失败")
                    except Exception as e:
                        log.error(f"导入模板 {name} 失败: {e}")

                InfoBar.success(title="成功", content=f"已导入 {imported_count} 个模板", parent=self)

        except Exception as e:
            log.error(f"导入模板失败: {e}")
            InfoBar.error(title="错误", content=f"导入失败: {str(e)}", parent=self)

    def closeEvent(self, event):
        """关闭事件"""
        self.refresh_timer.stop()
        self.preview_timer.stop()
        self.auto_match_timer.stop()
        super().closeEvent(event)
