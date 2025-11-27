from pathlib import Path
import threading
import time
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PyQt5.QtCore import pyqtSignal, QObject, Qt
from PyQt5.QtGui import QWheelEvent, QMouseEvent, QPainter, QCursor, QPixmap, QImage
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import QEventLoop

import re  # 用于清理非法字符
import os

from vstain.common.cons import SPECIAL_KEY_MAP
from vstain.config.settings import RESOURCE_DIR, MODULES_DIR, SCRIPTS_DIR
from src.vstain.common.style_sheet import StyleSheet
from src.vstain.common.config import cfg
from enum import IntEnum

import qframelesswindow as qfr
import qfluentwidgets as qf
import PyQt5.QtWidgets as qtw

from gas.util.hwnd_util import WindowInfo, window_activate
from gas.util.screenshot_util import screenshot, screenshot_bitblt
from gas.util.img_util import save_img
from gas.util.onnx_util import YOLOONNXDetector
from gas.util.keymouse_util import KeyMouseUtil
from gas.cons.key_code import KeyCode, get_windows_keycode

from src.vstain.utils.logger import get_logger
from vstain.utils.operation_recorder import OperationRecorder

log = get_logger()


class ScreenshotMode(IntEnum):
    PrintWindow = 0
    Bitblt = 1


class FrameUpdater(QObject):
    new_frame = pyqtSignal(np.ndarray)  # BGR
    fps_update = pyqtSignal(float)


# ====================== 可缩放/拖动的 ImageLabel ======================
class ZoomableImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: #111111;")
        self.setMinimumSize(800, 600)
        self.scale = 1.0
        self.min_scale = 0.2
        self.max_scale = 5.0
        self.offset_x = 0
        self.offset_y = 0
        self.is_dragging = False
        self.last_pos = None
        self.is_first_load = True  # 用于跟踪是否首次加载

        # 远程控制相关属性
        self.parent_widget = parent  # 保存父组件引用
        self.last_mouse_pos = None
        self.last_move_record_time = 0

    def wheelEvent(self, event: QWheelEvent):
        # 如果启用了远程控制，转发滚轮事件到目标窗口
        if hasattr(self.parent_widget, "is_remote_control") and self.parent_widget.is_remote_control:
            # 获取鼠标在图像上的实际坐标
            img_x, img_y = self._get_image_coordinates(event.pos())
            if img_x >= 0 and img_y >= 0:
                # 转发滚轮事件
                delta = event.angleDelta().y()
                count = 1 if delta > 0 else -1
                KeyMouseUtil.scroll_mouse(self.parent_widget.windows.hwnd, count, img_x, img_y)

            # 录制滚轮操作
            if hasattr(self.parent_widget, "is_recording") and self.parent_widget.is_recording:
                if img_x >= 0 and img_y >= 0:
                    delta = event.angleDelta().y()
                    count = 1 if delta > 0 else -1
                    # 录制滚轮操作
                    self.parent_widget.operation_recorder.add_mouse_scroll(img_x, img_y, count)
            return

        pix = self.pixmap()
        if not pix or pix.isNull():
            return

        pos = event.position() if hasattr(event, "position") else event.pos()
        pos_x = pos.x()
        pos_y = pos.y()

        old_scale = self.scale

        # 1. 计算新缩放
        if event.angleDelta().y() > 0:
            new_scale = self.scale * 1.25
        else:
            new_scale = self.scale * 0.8
        new_scale = max(self.min_scale, min(self.max_scale, new_scale))

        if abs(new_scale - old_scale) < 0.001:
            return  # 缩放没有变化

        # 2. 获取图像原始尺寸
        pix_w = pix.size().width()
        pix_h = pix.size().height()

        # 3. 计算旧状态 (基于 paintEvent 的逻辑)
        # 缩放前的自动居中偏移
        centering_x_old = (self.width() - pix_w * old_scale) / 2
        centering_y_old = (self.height() - pix_h * old_scale) / 2
        # 缩放前图像的实际左上角
        x_old = self.offset_x + centering_x_old
        y_old = self.offset_y + centering_y_old

        # 4. 计算鼠标在原图上的坐标
        # (防止 old_scale 为 0)
        if old_scale == 0:
            img_coord_x = 0
            img_coord_y = 0
        else:
            # (鼠标位置 - 图像左上角) / 缩放 = 图像坐标
            img_coord_x = (pos_x - x_old) / old_scale
            img_coord_y = (pos_y - y_old) / old_scale

        # 5. 计算新状态 (基于 paintEvent 的逻辑)
        # 缩放后的自动居中偏移
        centering_x_new = (self.width() - pix_w * new_scale) / 2
        centering_y_new = (self.height() - pix_h * new_scale) / 2

        # 6. 我们希望新的图像左上角 (x_new, y_new) 在哪里？
        # 目标：(鼠标位置 - 图像坐标 * 新缩放)
        x_new = pos_x - (img_coord_x * new_scale)
        y_new = pos_y - (img_coord_y * new_scale)

        # 7. paintEvent 使用的公式是: x_new = self.offset_x(新) + centering_x_new
        # 所以反向求解 self.offset_x(新)
        self.offset_x = x_new - centering_x_new
        self.offset_y = y_new - centering_y_new
        self.scale = new_scale  # 应用新缩放

        self.update()  # 触发重绘

    def mousePressEvent(self, event: QMouseEvent):
        # 如果启用了远程控制，转发鼠标点击事件到目标窗口
        if hasattr(self.parent_widget, "is_remote_control") and self.parent_widget.is_remote_control:
            img_x, img_y = self._get_image_coordinates(event.pos())
            if img_x >= 0 and img_y >= 0:
                if event.button() == Qt.LeftButton:
                    KeyMouseUtil.mouse_left_down(self.parent_widget.windows.hwnd, img_x, img_y)
                elif event.button() == Qt.RightButton:
                    KeyMouseUtil.mouse_right_down(self.parent_widget.windows.hwnd, img_x, img_y)
                elif event.button() == Qt.MiddleButton:
                    KeyMouseUtil.mouse_middle_down(self.parent_widget.windows.hwnd, img_x, img_y)
            # 录制鼠标按下操作
            if hasattr(self.parent_widget, "is_recording") and self.parent_widget.is_recording:
                if img_x >= 0 and img_y >= 0:
                    button_name = ""
                    if event.button() == Qt.LeftButton:
                        button_name = "left"
                    elif event.button() == Qt.RightButton:
                        button_name = "right"
                    elif event.button() == Qt.MiddleButton:
                        button_name = "middle"

                    if button_name:
                        self.parent_widget.operation_recorder.add_mouse_click(img_x, img_y, button_name, "down")
            return

        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            self.last_pos = event.pos()
            self.setCursor(QCursor(Qt.ClosedHandCursor))

    def mouseMoveEvent(self, event: QMouseEvent):
        if hasattr(self.parent_widget, "is_remote_control") and self.parent_widget.is_remote_control:
            img_x, img_y = self._get_image_coordinates(event.pos())
            if img_x >= 0 and img_y >= 0:
                # 如果上次有记录位置且左键按下，发送拖拽事件
                if self.last_mouse_pos and event.buttons() & Qt.LeftButton:
                    KeyMouseUtil.mouse_action(self.parent_widget.windows.hwnd, img_x, img_y, action_type="drag")
                else:
                    # 发送鼠标移动事件
                    KeyMouseUtil.mouse_move(self.parent_widget.windows.hwnd, img_x, img_y)

                self.last_mouse_pos = (img_x, img_y)

            # 录制鼠标移动操作（选择性录制，避免过多移动事件）
            if (
                hasattr(self.parent_widget, "is_recording")
                and self.parent_widget.is_recording
                and event.buttons() & Qt.LeftButton
            ):  # 只在拖拽时记录移动
                if img_x >= 0 and img_y >= 0 and time.time() - self.last_move_record_time > 0.05:
                    self.last_move_record_time = time.time()
                    self.parent_widget.operation_recorder.add_mouse_move(img_x, img_y)

            return

        # 原有本地拖拽逻辑保持不变
        if self.is_dragging:
            delta = event.pos() - self.last_pos
            self.offset_x += delta.x()
            self.offset_y += delta.y()
            self.last_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        # 如果启用了远程控制，转发鼠标释放事件到目标窗口
        if hasattr(self.parent_widget, "is_remote_control") and self.parent_widget.is_remote_control:
            img_x, img_y = self._get_image_coordinates(event.pos())
            if img_x >= 0 and img_y >= 0:
                if event.button() == Qt.LeftButton:
                    KeyMouseUtil.mouse_left_up(self.parent_widget.windows.hwnd, img_x, img_y)
                elif event.button() == Qt.RightButton:
                    KeyMouseUtil.mouse_right_up(self.parent_widget.windows.hwnd, img_x, img_y)
                elif event.button() == Qt.MiddleButton:
                    KeyMouseUtil.mouse_middle_up(self.parent_widget.windows.hwnd, img_x, img_y)
            self.last_mouse_pos = None

            # 录制鼠标释放操作
            if hasattr(self.parent_widget, "is_recording") and self.parent_widget.is_recording:
                if img_x >= 0 and img_y >= 0:
                    button_name = ""
                    if event.button() == Qt.LeftButton:
                        button_name = "left"
                    elif event.button() == Qt.RightButton:
                        button_name = "right"
                    elif event.button() == Qt.MiddleButton:
                        button_name = "middle"

                    if button_name:
                        self.parent_widget.operation_recorder.add_mouse_click(img_x, img_y, button_name, "up")

            return

        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.setCursor(QCursor(Qt.ArrowCursor))

    def _get_image_coordinates(self, pos):
        """将控件坐标转换为图像坐标"""
        if not self.pixmap() or self.pixmap().isNull():
            return -1, -1

        pix = self.pixmap()
        pix_w = pix.size().width()
        pix_h = pix.size().height()

        # 计算图像显示区域
        scaled_w = pix_w * self.scale
        scaled_h = pix_h * self.scale

        centering_x = (self.width() - scaled_w) / 2
        centering_y = (self.height() - scaled_h) / 2

        # 图像实际显示位置
        img_x = self.offset_x + centering_x
        img_y = self.offset_y + centering_y

        # 检查鼠标是否在图像范围内
        if img_x <= pos.x() <= img_x + scaled_w and img_y <= pos.y() <= img_y + scaled_h:
            # 转换为图像坐标
            rel_x = (pos.x() - img_x) / self.scale
            rel_y = (pos.y() - img_y) / self.scale

            # 确保坐标在图像范围内
            rel_x = max(0, min(pix_w - 1, rel_x))
            rel_y = max(0, min(pix_h - 1, rel_y))

            return int(rel_x), int(rel_y)

        return -1, -1

    def paintEvent(self, event):
        # 在首次绘制时，计算适应窗口的缩放
        if self.is_first_load and self.pixmap() and not self.pixmap().isNull():
            self.fit_to_window()  # 调用新方法计算缩放
            self.is_first_load = False  # 仅在第一次执行
            # 注意：fit_to_window 已经设置了 self.scale 和 offsets
            # paintEvent 会继续执行下去，使用新的缩放值进行绘制

        if not self.pixmap():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        pix = self.pixmap()
        scaled_pix = pix.scaled(pix.size() * self.scale, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 修改：偏移量现在基于(0,0)点，而不是控件中心
        # 这样 fit_to_window 设置 offset_x=0, offset_y=0 时能正确居中
        x = self.offset_x + (self.width() - scaled_pix.width()) / 2
        y = self.offset_y + (self.height() - scaled_pix.height()) / 2

        painter.drawPixmap(int(x), int(y), scaled_pix)

    def fit_to_window(self):
        """(新增) 计算缩放比例以使图像适应窗口大小"""
        if not self.pixmap() or self.pixmap().isNull():
            return

        pix_size = self.pixmap().size()
        lbl_size = self.size()  # 控件的当前大小

        if pix_size.width() == 0 or pix_size.height() == 0:
            return

        # 计算宽度和高度的缩放比例
        scale_w = lbl_size.width() / pix_size.width()
        scale_h = lbl_size.height() / pix_size.height()

        # 取较小的比例以确保图像完整显示（保持宽高比）
        self.scale = min(scale_w, scale_h)

        # 将缩放限制在设定的最大/最小范围内
        self.scale = max(self.min_scale, min(self.max_scale, self.scale))

        # 重置偏移量
        self.offset_x = 0
        self.offset_y = 0

    def reset_view(self):
        """(修改) 复位视图改为适应窗口大小"""
        self.fit_to_window()
        self.update()


class ImageCardWidget(qfr.FramelessWindow):
    def __init__(self, windows: WindowInfo = None, parent=None):
        super().__init__(parent)
        self.windows = windows
        self.setContentsMargins(10, 20, 10, 10)

        self.is_paused = False
        self.is_save_raw = False
        self.is_save_annotated = False
        self.is_detecting = False
        # 远程控制状态
        self.is_remote_control = False

        self.detector = None
        self.font = None
        self._load_resources_once()

        self.updater = FrameUpdater()
        self.updater.new_frame.connect(self._display_frame)
        self.updater.fps_update.connect(self._update_status)

        self._setup_ui()
        self._connect_signals()

        self.loop_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.loop_thread.start()

        # 操作录制器
        self.operation_recorder = OperationRecorder()
        self.is_recording = False
        self.last_move_record_time = 0

        StyleSheet.IMAGE_CARD_WIDGET.apply(self)

    def _load_resources_once(self):
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhl.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "simhei.ttf",
        ]
        for path in font_paths:
            try:
                self.font = ImageFont.truetype(path, 32)
                break
            except:
                continue
        else:
            self.font = ImageFont.truetype("arial.ttf", 32)  # 兜底

        # 模型加载
        model_path = MODULES_DIR / cfg.get(cfg.onnxModelName)
        if model_path.exists():
            try:
                input_size = int(cfg.get(cfg.onnxModelInput))
                self.detector = YOLOONNXDetector(
                    str(model_path),
                    conf_threshold=0.3,
                    input_size=(input_size, input_size),
                    providers=[cfg.get(cfg.onnxProvider)],
                )
            except Exception as e:
                log.error(f"模型加载失败: {e}")
                qf.InfoBar.error("模型加载失败", str(e), parent=self)
        else:
            qf.InfoBar.warning("未找到模型", str(model_path), parent=self)

    def _setup_ui(self):
        layout = qtw.QVBoxLayout(self)

        ctrl = qtw.QHBoxLayout()
        ctrl.addWidget(qf.BodyLabel("截图方式:"))

        self.mode_combo = qf.ComboBox(self)
        self.mode_combo.addItem("PrintWindow", userData=ScreenshotMode.PrintWindow)
        self.mode_combo.addItem("Bitblt", userData=ScreenshotMode.Bitblt)
        ctrl.addWidget(self.mode_combo)

        ctrl.addStretch(1)

        self.pause_btn = qf.PushButton("暂停")
        self.pause_btn.setCheckable(True)

        self.save_raw_btn = qf.PushButton("保存原图")
        self.save_raw_btn.setCheckable(True)

        self.save_ann_btn = qf.PushButton("保存标注图")
        self.save_ann_btn.setCheckable(True)

        self.detect_btn = qf.PrimaryPushButton("检测开")
        self.detect_btn.setCheckable(True)

        # 远程控制按钮
        self.remote_control_btn = qf.PushButton("远程控制关")
        self.remote_control_btn.setCheckable(True)
        self.remote_control_btn.enterEvent(False)

        # 录制控制按钮
        self.record_check = qf.CheckBox("是否录制")
        self.record_check.setChecked(True)

        self.save_record_btn = qf.PushButton("保存录制")
        self.save_record_btn.clicked.connect(self.save_recording)
        self.save_record_btn.setEnabled(False)

        self.reset_view_btn = qf.PushButton("复位视图")
        self.reset_view_btn.clicked.connect(self.reset_view)

        ctrl.addWidget(self.pause_btn)
        ctrl.addWidget(self.save_raw_btn)
        ctrl.addWidget(self.save_ann_btn)
        ctrl.addWidget(self.detect_btn)
        ctrl.addWidget(self.remote_control_btn)
        ctrl.addWidget(self.record_check)
        ctrl.addWidget(self.save_record_btn)
        ctrl.addWidget(self.reset_view_btn)

        self.status_label = qf.BodyLabel("就绪")
        self.status_label.setWordWrap(True)

        self.image_label = ZoomableImageLabel(self)  # ← 传递self作为parent
        self.image_label.setMinimumSize(800, 600)  # 给个默认大小

        layout.addLayout(ctrl)
        layout.addWidget(self.status_label)
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

    def _connect_signals(self):
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.detect_btn.clicked.connect(self.toggle_detect)
        self.save_raw_btn.clicked.connect(
            lambda: self._toggle_save("is_save_raw", self.save_raw_btn, "保存原图", "停止保存原图")
        )
        self.save_ann_btn.clicked.connect(
            lambda: self._toggle_save("is_save_annotated", self.save_ann_btn, "保存标注图", "停止保存标注图")
        )
        # 远程控制信号连接
        self.remote_control_btn.clicked.connect(self.toggle_remote_control)

    def start_recording(self):
        """开始录制操作"""
        if not self.windows:
            qf.InfoBar.warning("无法录制", "未选择目标窗口", parent=self)
            self.record_check.setChecked(False)
            return

        # 获取目标窗口的尺寸用于归一化
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetClientRect(self.windows.hwnd)
            width = right - left
            height = bottom - top
        except Exception as e:
            log.warning(f"获取窗口尺寸失败: {e}，使用默认尺寸")
            width, height = 1920, 1080

        self.operation_recorder.start_recording(width, height)
        self.is_recording = True
        self.record_check.setText("停止录制")
        self.save_record_btn.setEnabled(False)

    def stop_recording(self):
        """停止录制操作"""
        self.operation_recorder.stop_recording()
        self.is_recording = False
        self.record_check.setText("开始录制")
        self.record_check.setChecked(False)
        self.save_record_btn.setEnabled(True)

    def save_recording(self):
        """保存录制文件"""
        if not self.operation_recorder.operations:
            qf.InfoBar.warning("无法保存", "没有录制的操作", parent=self)
            return

        # 生成文件名
        timestamp = int(time.time())
        window_name = re.sub(r"[^\w]", "", self.windows.title) if self.windows else "unknown"
        filename = f"operation_{window_name}_{timestamp}.json"

        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SCRIPTS_DIR / filename

        if file_path:
            if self.operation_recorder.save_to_file(file_path):
                self.operation_recorder.clear_operations()
                qf.InfoBar.success("保存成功", f"操作记录已保存", duration=2000, parent=self)
            else:
                qf.InfoBar.error("保存失败", "请查看日志了解详情", parent=self)

    def toggle_pause(self):
        self.is_paused = self.pause_btn.isChecked()
        self.pause_btn.setText("继续" if self.is_paused else "暂停")

    def toggle_detect(self):
        self.is_detecting = self.detect_btn.isChecked()
        self.detect_btn.setText("检测关" if self.is_detecting else "检测开")

    def _toggle_save(self, attr, btn: qtw.QAbstractButton, text_on, text_off):
        checked = btn.isChecked()
        setattr(self, attr, checked)
        btn.setText(text_on if not checked else text_off)

    # 远程控制开关
    def toggle_remote_control(self):
        self.is_remote_control = self.remote_control_btn.isChecked()
        self.remote_control_btn.setText("远程控制关" if self.is_remote_control else "远程控制开")

        if self.is_remote_control:
            self.image_label.setFocus()

            self.record_check.setEnabled(False)
            if self.record_check.isChecked():
                self.start_recording()

            qf.InfoBar.success("远程控制已开启", "鼠标已隐藏，移动图像 = 转动游戏视角", duration=3000, parent=self)
        else:
            # 恢复正常光标
            self.image_label.setCursor(QCursor(Qt.ArrowCursor))
            self.record_check.setEnabled(True)
            if self.record_check.isChecked():
                self.stop_recording()

            qf.InfoBar.info("远程控制已关闭", "鼠标已恢复正常", duration=2000, parent=self)

    def keyPressEvent(self, event):
        if self.is_remote_control and self.windows.hwnd:
            self._handle_remote_key_event(event, True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self.is_remote_control and self.windows.hwnd:
            self._handle_remote_key_event(event, False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _handle_remote_key_event(self, event, is_press):
        key = event.key()
        text = event.text()

        if key in SPECIAL_KEY_MAP:
            code = SPECIAL_KEY_MAP[key]
            vk = get_windows_keycode(code)
        else:
            if Qt.Key_A <= key <= Qt.Key_Z:
                vk = key  # Qt.Key_A == 65 == VK_A，完美对齐！
            else:
                log.debug(f"未映射键: Qt.Key_{key} (0x{key:04X})")
                return

        # 录制键盘事件
        if hasattr(self, "is_recording") and self.is_recording:

            # 获取按键名称
            key_name = None
            if key in SPECIAL_KEY_MAP:
                code = SPECIAL_KEY_MAP[key]
                # 将KeyCode转换为可读名称
                key_name = str(code).split(".")[-1] if hasattr(code, "name") else f"Key_{key}"
            elif Qt.Key_A <= key <= Qt.Key_Z:
                key_name = chr(key)
            elif Qt.Key_0 <= key <= Qt.Key_9:
                key_name = chr(key)
            elif text and text.isprintable():
                key_name = text

            if key_name:
                event_type = "down" if is_press else "up"
                self.operation_recorder.add_keyboard(key_name, event_type)

        if is_press:
            KeyMouseUtil.key_down(self.windows.hwnd, vk)
        else:
            KeyMouseUtil.key_up(self.windows.hwnd, vk)

        # if is_press and text and text.isprintable():
        #     KeyMouseUtil.input_char(self.windows.hwnd, text)
        #     return

    def reset_view(self):
        self.image_label.reset_view()

    # ==================== 后台捕获循环 ====================
    def _capture_loop(self):
        frame_count = 0
        last_time = time.time()  # 1秒一次保存
        last_save_time = 0  # 上一次保存时间

        while True:
            if self.is_paused:
                time.sleep(0.1)
                continue

            scr = (screenshot if self.mode_combo.currentData() == ScreenshotMode.PrintWindow else screenshot_bitblt)(
                self.windows.hwnd
            )
            if scr is None:
                time.sleep(0.5)
                continue

            current_time = time.time()
            display_img = scr.copy()

            if self.is_detecting and self.detector:
                try:
                    _, detections, ms = self.detector.detect(scr)
                    display_img = self._draw_detections(scr, detections)
                    log.debug(f"onnx provider:{cfg.get(cfg.onnxProvider)} 检测耗时: {ms:.2f}ms")
                except Exception as e:
                    log.error(f"检测异常: {e}")

            self.updater.new_frame.emit(display_img)

            # 保存图像（1秒一次）
            if self.is_save_raw:
                if current_time - last_save_time >= 1.0:  #  # 每1秒保存一次
                    self._save_image(scr, "raw")
                    last_save_time = current_time

            if self.is_save_annotated and self.is_detecting:
                if current_time - last_save_time >= 1.0:
                    self._save_image(display_img, "annotated")
                    last_save_time = current_time

            # FPS
            frame_count += 1
            if current_time - last_time >= 1.0:
                fps = round(frame_count / (current_time - last_time) * 1.0, 1)
                self.updater.fps_update.emit(fps)
                frame_count = 0
                last_time = current_time

            # # 此次截图耗时不可算入 不然远小于60
            internal = 0.015 - (time.time() - current_time)
            if internal > 0.0:
                time.sleep(internal)  # ~60 FPS

    def _draw_detections(self, img_bgr, detections):
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).convert("RGBA")
        draw = ImageDraw.Draw(pil)

        for det in detections:
            x1, y1, x2, y2 = map(int, det["box"])
            name = det.get("class_name", f"id{det['class_id']}")
            conf = det["confidence"]
            label = f"{name} {conf:.2f}"

            bbox = draw.textbbox((0, 0), label, font=self.font)
            w = bbox[2] - bbox[0] + 24
            h = bbox[3] - bbox[1] + 16

            if y1 >= h + 10:
                ly = y1 - h - 4
                ty = y1 - h + 10
            else:
                ly = y2 + 4
                ty = y2 + 12

            # 半透明绿底 + 白字黑边
            # draw.rectangle([x1, ly, x1 + w, ly + h], fill=(0, 220, 0, 200))
            draw.rectangle([x1, y1, x2, y2], outline=(0, 255, 0, 255), width=1)

            # 白字黑影（超清晰）
            for dx, dy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
                draw.text((x1 + 12 + dx, ty + dy), label, font=self.font, fill=(0, 0, 0))
            draw.text((x1 + 12, ty), label, font=self.font, fill=(255, 255, 255))

        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGBA2BGR)

    def _save_image(self, img, folder):
        try:
            title = re.sub(r"[^\\p{L}]", "", self.windows.title, flags=re.UNICODE)
            path = Path(RESOURCE_DIR) / "screenshot" / folder / title
            path.mkdir(parents=True, exist_ok=True)
            filename = f"{int(time.time()*1000)}.png"
            save_img(img, path / filename)
        except Exception as e:
            log.error(e)

    def _update_status(self, fps):
        mode = "PrintWindow" if self.mode_combo.currentData() == ScreenshotMode.PrintWindow else "Bitblt"
        detect = "检测开" if self.is_detecting else "检测关"
        raw = "原图√" if self.is_save_raw else ""
        ann = "标注√" if self.is_save_annotated else ""
        scale_info = f"缩放{self.image_label.scale:.1f}x"
        remote_ctrl = "远程控制√" if self.is_remote_control else ""

        # 录制状态显示
        recording_status = "录制中" if self.is_recording else ""
        operation_count = self.operation_recorder.operation_count
        record_info = f"操作{operation_count}" if operation_count > 0 else ""

        self.status_label.setText(
            f"{self.windows.title[:30]} | {mode} | FPS {fps} | {detect} {raw}{ann} | {scale_info} | {remote_ctrl} | {recording_status} {record_info}"
        )

    def _display_frame(self, frame_bgr: np.ndarray):
        if frame_bgr is None:
            return
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self.image_label.setPixmap(pixmap)

    def closeEvent(self, a0):
        return super().closeEvent(a0)
