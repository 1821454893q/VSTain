"""窗口特征捕获和匹配工具"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QListWidgetItem,
    QProgressBar,
    QFileDialog,
)

from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    BodyLabel,
    ComboBox,
    LineEdit,
    DoubleSpinBox,
    SpinBox,
    InfoBar,
    CheckBox,
    TextEdit,
    ListWidget,
    SingleDirectionScrollArea,
    MessageBoxBase,
)

from gas.util.hwnd_util import get_hwnd_by_class_and_title, WindowInfo, list_all_windows
from gas.util.screenshot_util import screenshot, screenshot_bitblt
from gas.util.img_util import bgr2rgb
from src.vstain.components.image_viewer import ImageViewer, ViewerTool, Region
from src.vstain.common.style_sheet import StyleSheet
from src.vstain.common.config import cfg
from src.vstain.utils.logger import get_logger

log = get_logger()


@dataclass
class ORBConfig:
    """ORB配置"""

    name: str
    description: str
    nfeatures: int
    scaleFactor: float
    nlevels: int
    edgeThreshold: int = 31
    firstLevel: int = 0
    WTA_K: int = 2
    scoreType: int = cv2.ORB_HARRIS_SCORE
    patchSize: int = 31
    fastThreshold: int = 20
    # 小图标专用
    use_harris: bool = False
    # 用于调试
    debug: bool = False


@dataclass
class FeatureTemplate:
    """特征模板"""

    name: str
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


class WindowFeatureCaptureWidget(QWidget):
    """窗口特征捕获和匹配工具"""

    def __init__(self, objectName: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(objectName)

        # 窗口/模板
        self.current_hwnd = None
        self.current_window_title = None
        self.current_window_class = None
        self.feature_templates: Dict[str, FeatureTemplate] = {}
        self.templates_file = Path("feature_templates.json")

        # 状态
        self.is_matching = False
        self.match_timer = QTimer()
        self.match_timer.timeout.connect(self._perform_match)
        self.match_interval = 1000

        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self._update_preview)

        self.current_window_image = None
        self.current_match_results = None
        self.selected_region: Optional[Region] = None

        # 调试可视化开关
        self.debug_visual = False

        # ORB 检测器（两个独立）
        self.orb_template = self._create_default_orb_template()  # 模板专用
        self.orb_scene = cv2.ORB_create(
            nfeatures=20000,  # 全图提取更多点
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=31,
            patchSize=31,
            fastThreshold=10,
        )

        self._setup_ui()
        self._set_connections()

        StyleSheet.FEATURE_CAPTURE_WIDGET.apply(self)
        self._load_templates()

    def _create_default_orb_template(self):
        """默认模板 ORB 配置（通用）"""
        return cv2.ORB_create(
            nfeatures=200,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=31,
            patchSize=31,
            fastThreshold=10,
        )

    # -----------------------------
    # UI
    # -----------------------------
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

        # 主布局
        self._setup_main_layout(main_layout)

    def _create_left_side_widgets(self):
        """创建左侧所有部件"""
        # 窗口选择
        self.window_list = ListWidget()
        self.refresh_btn = PushButton("刷新窗口列表")
        self.connect_btn = PrimaryPushButton("连接到窗口")

        # 自定义 ORB
        self.custom_orb_btn = PushButton("自定义ORB参数（模板专用）")

        # 模板捕获
        self.template_name_edit = LineEdit()
        self.template_name_edit.setPlaceholderText("输入模板名称")

        self.confidence_spin = DoubleSpinBox()
        self.confidence_spin.setRange(0.1, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setValue(0.5)  # 默认更宽松

        self.capture_btn = PrimaryPushButton("捕获特征模板")
        self.capture_full_btn = PushButton("捕获全屏")
        self.clear_region_btn = PushButton("清除选区")

        # 模板列表
        self.template_list = ListWidget()
        self.delete_template_btn = PushButton("删除模板")
        self.export_templates_btn = PushButton("导出模板")
        self.import_templates_btn = PushButton("导入模板")

        # 匹配控制
        self.match_interval_spin = SpinBox()
        self.match_interval_spin.setRange(100, 10000)
        self.match_interval_spin.setSingleStep(100)
        self.match_interval_spin.setValue(self.match_interval)

        self.debug_visual_check = CheckBox("匹配调试可视化")
        self.debug_visual_check.setChecked(False)

        self.start_match_btn = PrimaryPushButton("开始自动匹配")
        self.match_once_btn = PushButton("单次匹配")

    def _create_right_side_widgets(self):
        """创建右侧所有部件"""
        self.preview_label = ImageViewer()
        self.preview_label.setMinimumSize(400, 300)
        self.preview_label.set_tool(ViewerTool.SELECT)

        self.viewer_select_btn = PushButton("选择")
        self.viewer_pan_btn = PushButton("拖动")
        self.viewer_reset_btn = PushButton("复位")
        self._update_viewer_tool_button_state(ViewerTool.SELECT)

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
        self.left_scroll = SingleDirectionScrollArea(orient=Qt.Vertical)
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        left_content = QWidget()
        layout = QVBoxLayout(left_content)
        layout.setContentsMargins(5, 5, 15, 5)
        layout.setSpacing(10)

        # 窗口选择组
        g = QGroupBox("窗口选择")
        l = QVBoxLayout(g)
        l.addWidget(self.window_list)
        btn_l = QHBoxLayout()
        btn_l.addWidget(self.refresh_btn)
        btn_l.addWidget(self.connect_btn)
        l.addLayout(btn_l)
        layout.addWidget(g)

        # ORB 配置
        g = QGroupBox("ORB 参数")
        l = QVBoxLayout(g)
        l.addWidget(self.custom_orb_btn)
        layout.addWidget(g)

        # 模板捕获
        g = QGroupBox("模板捕获")
        l = QVBoxLayout(g)
        l.addWidget(BodyLabel("模板名称:"))
        l.addWidget(self.template_name_edit)
        conf_l = QHBoxLayout()
        conf_l.addWidget(BodyLabel("置信度阈值:"))
        conf_l.addWidget(self.confidence_spin)
        l.addLayout(conf_l)
        btn_l = QHBoxLayout()
        btn_l.addWidget(self.capture_btn)
        btn_l.addWidget(self.capture_full_btn)
        l.addLayout(btn_l)
        l.addWidget(self.clear_region_btn)
        layout.addWidget(g)

        # 模板列表
        g = QGroupBox("已保存模板")
        l = QVBoxLayout(g)
        l.addWidget(self.template_list)
        btn_l = QHBoxLayout()
        btn_l.addWidget(self.delete_template_btn)
        btn_l.addWidget(self.export_templates_btn)
        btn_l.addWidget(self.import_templates_btn)
        l.addLayout(btn_l)
        layout.addWidget(g)

        # 匹配控制
        g = QGroupBox("匹配控制")
        l = QVBoxLayout(g)
        int_l = QHBoxLayout()
        int_l.addWidget(BodyLabel("间隔(ms):"))
        int_l.addWidget(self.match_interval_spin)
        l.addLayout(int_l)
        l.addWidget(self.debug_visual_check)
        btn_l = QHBoxLayout()
        btn_l.addWidget(self.start_match_btn)
        btn_l.addWidget(self.match_once_btn)
        l.addLayout(btn_l)
        layout.addWidget(g)

        layout.addStretch()
        self.left_scroll.setWidget(left_content)
        self.left_scroll.setMinimumWidth(340)
        self.left_scroll.enableTransparentBackground()

    def _setup_right_side_layout(self):
        """设置右侧布局"""
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)

        g = QGroupBox("窗口预览")
        l = QVBoxLayout(g)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.viewer_select_btn)
        toolbar.addWidget(self.viewer_pan_btn)
        toolbar.addWidget(self.viewer_reset_btn)
        toolbar.addStretch()
        l.addLayout(toolbar)
        l.addWidget(self.preview_label)
        ctrl = QHBoxLayout()
        ctrl.addWidget(self.refresh_preview_btn)
        ctrl.addStretch()
        ctrl.addWidget(self.auto_preview_check)
        l.addLayout(ctrl)
        right_layout.addWidget(g)

        g = QGroupBox("匹配结果")
        l = QVBoxLayout(g)
        l.addWidget(self.result_text)
        l.addWidget(self.match_progress)
        right_layout.addWidget(g)

    def _setup_main_layout(self, main_layout):
        """设置主布局"""
        main_layout.addWidget(self.left_scroll)
        main_layout.addWidget(self.right_widget)
        main_layout.setStretchFactor(self.left_scroll, 1)
        main_layout.setStretchFactor(self.right_widget, 2)

    def _set_connections(self):
        """设置信号连接"""
        self.refresh_btn.clicked.connect(self._refresh_window_list)
        self.connect_btn.clicked.connect(self._connect_to_window)
        self.capture_btn.clicked.connect(self._capture_feature_template)
        self.refresh_preview_btn.clicked.connect(self._update_preview)
        self.start_match_btn.clicked.connect(self._toggle_auto_match)
        self.clear_region_btn.clicked.connect(self._clear_region_selection)
        self.capture_full_btn.clicked.connect(self._capture_full_screen)
        self.custom_orb_btn.clicked.connect(self._show_custom_orb_dialog)
        self.match_once_btn.clicked.connect(self._perform_match)

        self.window_list.itemClicked.connect(self._on_window_selected)
        self.template_list.itemClicked.connect(self._on_template_selected)

        self.delete_template_btn.clicked.connect(self._delete_template)
        self.export_templates_btn.clicked.connect(self._export_templates)
        self.import_templates_btn.clicked.connect(self._import_templates)

        self.auto_preview_check.toggled.connect(self._toggle_auto_preview)
        self.debug_visual_check.toggled.connect(lambda c: setattr(self, "debug_visual", c))

        self.match_interval_spin.valueChanged.connect(lambda v: self.match_timer.setInterval(v))

        self.viewer_select_btn.clicked.connect(lambda: self._set_viewer_tool(ViewerTool.SELECT))
        self.viewer_pan_btn.clicked.connect(lambda: self._set_viewer_tool(ViewerTool.PAN))
        self.viewer_reset_btn.clicked.connect(self._reset_viewer)

        self.preview_label.region_selected.connect(self._on_region_selected)

    def _set_viewer_tool(self, tool: ViewerTool) -> None:
        """设置预览查看器工具（选择/拖动）"""
        self.preview_label.set_tool(tool)
        self._update_viewer_tool_button_state(tool)

    def _reset_viewer(self) -> None:
        """复位预览查看器：缩放/位置，并清除选区"""
        self.preview_label.reset_view()
        self.preview_label.clear_selection()
        self.selected_region = None

    def _update_viewer_tool_button_state(self, tool: ViewerTool) -> None:
        """简单的按钮禁用状态"""
        self.viewer_select_btn.setEnabled(tool != ViewerTool.SELECT)
        self.viewer_pan_btn.setEnabled(tool != ViewerTool.PAN)

    # -----------------------------
    # ORB config
    # -----------------------------
    def _get_orb_configs(self):
        """获取ORB配置预设"""
        return [
            ORBConfig(
                name="small_icons",
                description="小图标优化 (25x25-50x50)",
                nfeatures=50,
                scaleFactor=1.1,
                nlevels=4,
                edgeThreshold=15,
                patchSize=15,
                fastThreshold=5,
                use_harris=True,
            ),
            ORBConfig(
                name="ui_elements",
                description="UI元素通用 (50x50-200x200)",
                nfeatures=200,
                scaleFactor=1.2,
                nlevels=8,
                edgeThreshold=31,
                patchSize=31,
                fastThreshold=10,
            ),
            ORBConfig(
                name="large_regions",
                description="大区域优化 (200x200+)",
                nfeatures=500,
                scaleFactor=1.2,
                nlevels=8,
                edgeThreshold=31,
                patchSize=31,
                fastThreshold=20,
            ),
            ORBConfig(
                name="high_accuracy",
                description="高精度模式 (更多特征点)",
                nfeatures=1000,
                scaleFactor=1.1,
                nlevels=12,
                edgeThreshold=31,
                patchSize=31,
                fastThreshold=15,
                use_harris=True,
            ),
        ]

    def _show_custom_orb_dialog(self):
        """显示自定义ORB参数对话框"""
        dialog = MessageBoxBase(self)

        v_layout = QVBoxLayout()

        # 特征点数量
        nfeatures_layout = QHBoxLayout()
        nfeatures_layout.addWidget(BodyLabel("特征点数量:"))
        nfeatures_spin = SpinBox()
        nfeatures_spin.setRange(10, 5000)
        nfeatures_layout.addWidget(nfeatures_spin)
        v_layout.addLayout(nfeatures_layout)

        # 缩放因子
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(BodyLabel("缩放因子:"))
        scale_spin = DoubleSpinBox()
        scale_spin.setRange(1.05, 2.0)
        scale_spin.setSingleStep(0.05)
        scale_layout.addWidget(scale_spin)
        v_layout.addLayout(scale_layout)

        # 金字塔层数
        levels_layout = QHBoxLayout()
        levels_layout.addWidget(BodyLabel("金字塔层数:"))
        levels_spin = SpinBox()
        levels_spin.setRange(1, 20)
        levels_layout.addWidget(levels_spin)
        v_layout.addLayout(levels_layout)

        # Patch大小
        patch_layout = QHBoxLayout()
        patch_layout.addWidget(BodyLabel("Patch大小:"))
        patch_spin = SpinBox()
        patch_spin.setRange(5, 50)
        patch_layout.addWidget(patch_spin)
        v_layout.addLayout(patch_layout)

        # FAST阈值
        fast_layout = QHBoxLayout()
        fast_layout.addWidget(BodyLabel("FAST阈值:"))
        fast_spin = SpinBox()
        fast_spin.setRange(1, 50)
        fast_layout.addWidget(fast_spin)
        v_layout.addLayout(fast_layout)

        dialog.viewLayout.addLayout(v_layout)

        def on_confirm():
            self.orb_template = cv2.ORB_create(
                nfeatures=nfeatures_spin.value(),
                scaleFactor=scale_spin.value(),
                nlevels=levels_spin.value(),
                patchSize=patch_spin.value(),
                fastThreshold=fast_spin.value(),
            )
            InfoBar.success(title="成功", content="自定义ORB参数已应用（模板专用）", parent=self)
            dialog.close()

        dialog.yesButton.setText("确定")
        dialog.yesButton.clicked.connect(on_confirm)
        dialog.cancelButton.setText("取消")
        dialog.exec()

    # -----------------------------
    # Window / template
    # -----------------------------
    def _refresh_window_list(self):
        """刷新窗口列表"""
        self.window_list.clear()

        try:
            windows = self._get_available_windows()
            for win in windows:
                item = QListWidgetItem(f"{win.title} ({win.class_name})")
                item.setData(Qt.ItemDataRole.UserRole, win)
                self.window_list.addItem(item)

            InfoBar.success(title="成功", content=f"已加载 {len(windows)} 个窗口", parent=self)
        except Exception as e:
            log.error(f"刷新窗口列表失败: {e}")
            InfoBar.error(title="错误", content=f"刷新失败: {e}", parent=self)

    def _get_available_windows(self) -> Optional[List[WindowInfo]]:
        """获取可用窗口列表（保留你原实现）"""
        all = list_all_windows()

        res = []

        for win in all:
            if self._check_window(win):
                res.append(win)
            for c in win.children:
                if self._check_window(c):
                    res.append(c)

        return res

    def _check_window(self, win: WindowInfo) -> bool:
        if not win.is_visible:  # 窗口不可见
            return False

        title = cfg.get(cfg.hwndWindowsTitle)
        className = cfg.get(cfg.hwndClassname)
        if title and title not in win.title or className and className not in win.class_name:
            return False

        return True

    def _on_window_selected(self, item):
        """窗口选择变化"""
        win = item.data(Qt.ItemDataRole.UserRole)
        self.current_window_title = win.title
        self.current_window_class = win.class_name

    def _connect_to_window(self):
        """连接到选择的窗口"""
        if not self.current_window_title or not self.current_window_class:
            InfoBar.warning(title="提示", content="请先选择窗口", parent=self)
            return

        hwnd = get_hwnd_by_class_and_title(self.current_window_class, self.current_window_title)
        if hwnd:
            self.current_hwnd = hwnd[0]
            InfoBar.success(title="成功", content=f"已连接到窗口: {self.current_window_title}", parent=self)
            self._update_preview()
        else:
            InfoBar.error(title="错误", content="连接失败，未找到对应窗口", parent=self)

    def _update_preview(self):
        """更新窗口预览"""
        if not self.current_hwnd:
            return

        try:
            screenshot_img = screenshot(self.current_hwnd)
            if screenshot_img is not None:
                self.current_window_image = screenshot_img.copy()

                height, width, channel = screenshot_img.shape
                bytes_per_line = 3 * width
                q_img = QImage(bgr2rgb(screenshot_img).data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

                # 直接传入原尺寸图像，由 ImageViewer 负责自适应显示
                pixmap = QPixmap.fromImage(q_img)
                self.preview_label.set_image(pixmap)

        except Exception as e:
            log.error(f"更新预览失败: {e}")

    def _toggle_auto_preview(self, checked):
        """切换自动预览"""
        if checked and self.current_hwnd:
            self.preview_timer.start(500)  # 0.5秒刷新一次
        else:
            self.preview_timer.stop()

    def _on_region_selected(self, region: Region):
        """区域选择完成（region.image 为原始图像像素坐标）"""
        self.selected_region = region
        w, h = region.image.width(), region.image.height()
        InfoBar.info(title="提示", content=f"已选择区域: {w}x{h}", parent=self)

    def _clear_region_selection(self):
        """清除区域选择"""
        self.preview_label.clear_selection()
        self.selected_region = None

    def _capture_full_screen(self):
        """捕获全屏"""
        self.selected_region = None
        self.preview_label.clear_selection()
        InfoBar.info(title="提示", content="已切换为全屏捕获", parent=self)

    def _capture_feature_template(self):
        """捕获特征模板"""
        if self.current_window_image is None or not self.template_name_edit.text().strip():
            InfoBar.warning(title="警告", content="请先连接窗口并输入模板名称", parent=self)
            return

        template_name = self.template_name_edit.text().strip()
        if template_name in self.feature_templates:
            InfoBar.warning(title="警告", content="模板名称已存在", parent=self)
            return

        # 获取选择的区域或使用全屏
        region = getattr(self, "selected_region", None)

        if region is not None:
            # region.image 是基于原始图像像素坐标（无需额外缩放换算）
            r = region.image
            x, y, width, height = r.x(), r.y(), r.width(), r.height()

            # 截取区域
            template_image = self.current_window_image[y : y + height, x : x + width]
            position = {"x": x, "y": y, "width": width, "height": height}
            log.debug(f"截图特征 position {position}, 图像尺寸: {template_image.shape}")
        else:
            # 使用全屏
            template_image = self.current_window_image.copy()
            height, width = template_image.shape[:2]
            position = {"x": 0, "y": 0, "width": width, "height": height}

        # 提取特征
        keypoints, descriptors = self.orb_template.detectAndCompute(template_image, None)

        log.debug(
            f"提取特征结果: 关键点={len(keypoints) if keypoints else 0}, 描述符形状={descriptors.shape if descriptors is not None else 'None'}"
        )

        if descriptors is None or len(descriptors) == 0:
            InfoBar.warning(title="警告", content="未能提取到有效特征，请调整区域或ORB参数", parent=self)
            return

        template = FeatureTemplate(
            name=template_name,
            position=position,
            confidence_threshold=float(self.confidence_spin.value()),
            keypoints=keypoints,
            descriptors=descriptors,
        )

        self.feature_templates[template_name] = template
        self.template_list.addItem(template_name)

        # 可视化（受调试开关控制）
        if self.debug_visual and keypoints:
            vis = cv2.drawKeypoints(
                template_image.copy(),
                keypoints,
                None,
                color=(0, 255, 0),
                flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
            )
            vis = cv2.resize(vis, (500, 500))
            cv2.imshow(f"Template Captured: {template_name} ({len(keypoints)} pts)", vis)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        InfoBar.success(title="成功", content=f"已捕获模板: {template_name}", parent=self)

        # 清理选区
        self.preview_label.clear_selection()
        self.selected_region = None

        # 保存模板
        self._save_templates()

    # -----------------------------
    # Matching
    # -----------------------------
    def _toggle_auto_match(self):
        """切换自动匹配"""
        if not self.is_matching:
            if not self.current_hwnd:
                InfoBar.warning(title="提示", content="请先连接窗口", parent=self)
                return
            if not self.feature_templates:
                InfoBar.warning(title="提示", content="请先捕获至少一个模板", parent=self)
                return

            self.is_matching = True
            self.start_match_btn.setText("停止自动匹配")
            self.match_progress.setVisible(True)

            self.auto_match_timer.start(self.match_interval_spin.value())
            InfoBar.success(title="开始", content="已开始自动匹配", parent=self)
        else:
            self.is_matching = False
            self.start_match_btn.setText("开始自动匹配")
            self.match_progress.setVisible(False)

            self.auto_match_timer.stop()
            InfoBar.info(title="停止", content="已停止自动匹配", parent=self)

    @property
    def auto_match_timer(self):
        """兼容原逻辑：统一用 match_timer"""
        return self.match_timer

    def _perform_match(self):
        """执行匹配"""
        if not self.current_hwnd or not self.feature_templates:
            return

        try:
            screenshot_img = screenshot(self.current_hwnd)
            if screenshot_img is None:
                return

            self.current_window_image = screenshot_img.copy()

            results = []
            for name, template in self.feature_templates.items():
                res = self._match_template(template, screenshot_img)
                if res is not None:
                    results.append(res)

            self.current_match_results = results
            self._update_result_text(results)
            self._update_preview_with_matches()

        except Exception as e:
            log.error(f"匹配失败: {e}")

    def _match_template(self, template: FeatureTemplate, image: np.ndarray):
        """匹配单个模板 knn + ratio test + homography"""
        if template.descriptors is None or len(template.descriptors) == 0:
            return None

        log.debug(f"模板 {template.name} 特征点数: {len(template.descriptors)}")

        kp2, des2 = self.orb_scene.detectAndCompute(image, None)
        if des2 is None or len(des2) < 50:
            return None

        log.debug(f"当前图像特征点数: {len(des2) if des2 is not None else 0}")

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        knn_matches = bf.knnMatch(template.descriptors, des2, k=2)

        good_matches = []
        for m_n in knn_matches:
            if len(m_n) == 2:
                m, n = m_n
                if m.distance < 0.8 * n.distance:  # 放宽
                    good_matches.append(m)

        log.debug(f"Good matches: {len(good_matches)}")

        if len(good_matches) < 6:  # 更宽容
            return None

        src_pts = np.float32([template.keypoints[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if H is None:
            return None

        matches_mask = mask.ravel().tolist()
        inliers = sum(matches_mask)
        confidence = inliers / len(good_matches)

        log.debug(f"Inliers: {inliers}/{len(good_matches)} Confidence: {confidence:.3f}")

        if confidence < template.confidence_threshold:
            return None

        h, w = template.position["height"], template.position["width"]
        template_corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        matched_corners = cv2.perspectiveTransform(template_corners, H)
        matched_corners = matched_corners.reshape(-1, 2).astype(int)

        x_coords = matched_corners[:, 0]
        y_coords = matched_corners[:, 1]
        x_min, x_max = max(0, x_coords.min()), min(image.shape[1], x_coords.max())
        y_min, y_max = max(0, y_coords.min()), min(image.shape[0], y_coords.max())

        pos = {
            "x": int(x_min),
            "y": int(y_min),
            "width": int(x_max - x_min),
            "height": int(y_max - y_min),
        }

        result = {
            "template": template.name,
            "position": pos,
            "confidence": confidence,
            "good_matches": good_matches,  # 用于后续绘图
            "kp2": kp2,
            "mask": matches_mask,
        }

        # 匹配调试可视化
        if self.debug_visual:
            h, w = template.position["height"], template.position["width"]
            template_vis = np.zeros((h, w, 3), np.uint8) + 255
            template_vis = cv2.drawKeypoints(
                template_vis,
                template.keypoints,
                None,
                color=(0, 255, 0),
                flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
            )

            scene_vis = cv2.drawKeypoints(
                image.copy(), kp2, None, color=(0, 255, 0), flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS
            )

            draw_img = cv2.drawMatches(
                template_vis,
                template.keypoints,
                scene_vis,
                kp2,
                good_matches,
                None,
                matchColor=(0, 255, 0),
                matchesMask=matches_mask,
                flags=2,
            )
            draw_img = cv2.resize(draw_img, (1400, 700))
            cv2.imshow(
                f"MATCH SUCCESS: {template.name} | Good:{len(good_matches)} Inliers:{inliers} Conf:{confidence:.3f}",
                draw_img,
            )
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        return result

    def _update_result_text(self, results):
        """更新结果文本"""
        if not results:
            self.result_text.setText("未找到匹配结果")
            return

        lines = []
        for r in sorted(results, key=lambda x: x["confidence"], reverse=True):
            lines.append(f"模板: {r['template']}  置信度: {r['confidence']:.3f}  位置: {r['position']}")
        self.result_text.setText("\n".join(lines))

    def _update_preview_with_matches(self):
        """更新预览图像并标记匹配点"""
        if self.current_window_image is None or self.current_match_results is None:
            return

        try:
            display_image = self.current_window_image.copy()

            for result in self.current_match_results:
                pos = result["position"]
                confidence = result["confidence"]

                # 画多边形框（更准确，支持旋转）
                corners = np.array(
                    [
                        [pos["x"], pos["y"]],
                        [pos["x"] + pos["width"], pos["y"]],
                        [pos["x"] + pos["width"], pos["y"] + pos["height"]],
                        [pos["x"], pos["y"] + pos["height"]],
                    ],
                    np.int32,
                )
                cv2.polylines(display_image, [corners], isClosed=True, color=(0, 255, 0), thickness=3)

                # 文本
                label = f"{result['template']} ({confidence:.3f})"
                cv2.putText(
                    display_image,
                    label,
                    (pos["x"], max(0, pos["y"] - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )

            height, width, channel = display_image.shape
            bytes_per_line = 3 * width
            q_img = QImage(bgr2rgb(display_image).data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

            pixmap = QPixmap.fromImage(q_img)
            self.preview_label.set_image(pixmap)

        except Exception as e:
            log.error(f"更新匹配预览失败: {e}")

    # -----------------------------
    # Template persistence
    # -----------------------------
    def _save_templates(self):
        """保存模板到文件（只保存可JSON化字段）"""
        try:
            data = {}
            for name, tpl in self.feature_templates.items():
                data[name] = tpl.to_dict()

            with open(self.templates_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            log.error(f"保存模板失败: {e}")

    def _load_templates(self):
        """加载模板"""
        if not self.templates_file.exists():
            return

        try:
            with open(self.templates_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for name, item in data.items():
                self.feature_templates[name] = FeatureTemplate.from_dict(item)
                self.template_list.addItem(name)

        except Exception as e:
            log.error(f"加载模板失败: {e}")

    def _export_templates(self):
        """导出模板"""
        if not self.feature_templates:
            InfoBar.warning(title="提示", content="没有模板可导出", parent=self)
            return

        path, _ = QFileDialog.getSaveFileName(self, "导出模板", "feature_templates.json", "JSON (*.json)")
        if not path:
            return

        try:
            export_data = {}
            for name, tpl in self.feature_templates.items():
                export_data[name] = tpl.to_dict()

            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            InfoBar.success(title="成功", content=f"已导出到: {path}", parent=self)
        except Exception as e:
            InfoBar.error(title="错误", content=f"导出失败: {e}", parent=self)

    def _import_templates(self):
        """导入模板"""
        path, _ = QFileDialog.getOpenFileName(self, "导入模板", "", "JSON (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            for name, item in data.items():
                self.feature_templates[name] = FeatureTemplate.from_dict(item)
                self.template_list.addItem(name)
                count += 1

            InfoBar.success(title="成功", content=f"已导入 {count} 个模板", parent=self)
        except Exception as e:
            InfoBar.error(title="错误", content=f"导入失败: {e}", parent=self)

    # -----------------------------
    # Template list actions
    # -----------------------------
    def _on_template_selected(self, item):
        """模板选择变化"""
        template_name = item.text()
        if template_name in self.feature_templates:
            template = self.feature_templates[template_name]
            self.result_text.setText(
                f"模板: {template_name}\n"
                f"位置: {template.position}\n"
                f"尺寸: {template.position['width']}x{template.position['height']}\n"
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
            self._save_templates()
