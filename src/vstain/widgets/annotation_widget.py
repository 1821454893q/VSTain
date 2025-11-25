"""图片标注工具"""

import datetime
import math
import os
import shutil
from pathlib import Path

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QCursor, QWheelEvent, QMouseEvent
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QListWidget,
    QComboBox,
    QSpinBox,
    QFileDialog,
    QApplication,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
)

from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    CheckBox,
    DoubleSpinBox,
    InfoBarPosition,
    InfoBar,
)

from src.vstain.config.settings import PROJECT_ROOT, MODULES_DIR
from src.vstain.utils.logger import get_logger
from src.vstain.common.style_sheet import StyleSheet
from gas.util.onnx_util import YOLOONNXDetector

log = get_logger()


class AnnotationCanvas(QLabel):
    """核心画布 - 使用归一化坐标"""

    bboxDrawn = pyqtSignal(list)  # [class_id, cx_norm, cy_norm, w_norm, h_norm]
    # 已标注框
    colors = [
        (0, 255, 0),  # 绿
        (255, 100, 0),  # 橙
        (0, 150, 255),  # 蓝
        (255, 0, 255),  # 紫
        (0, 255, 255),  # 青
        (255, 255, 0),  # 黄
        (100, 255, 100),  # 浅绿
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#1e1e1e; border: 2px solid #333; border-radius: 6px;")
        self.setMinimumSize(600, 450)

        self.original_pixmap = None
        self.annotations = []  # 归一化标注 [[class_id, cx, cy, w, h]]
        self.current_class_id = 0

        # 默认模式为平移，Q键切换为标注模式
        self.is_drawing_mode = False  # False=平移模式, True=标注模式
        self.is_drawing = False
        self.start_pos = QPointF()
        self.current_pos = QPointF()

        # 存储当前鼠标位置用于绘制十字准星
        self.current_mouse_pos = QPointF()

        # 缩放相关变量
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.zoom_step = 0.1
        self.pan_start_pos = QPointF()
        self.is_panning = False
        self.pan_offset = QPointF(0, 0)

        self.bbox_pen = QPen(QColor(0, 255, 0), 2)
        self.drawing_pen = QPen(QColor(255, 80, 80), 2, Qt.DashLine)

        # 十字准星画笔
        self.crosshair_pen = QPen(QColor(255, 255, 255, 180), 1, Qt.DashLine)

    def _get_image_rect(self):
        """计算图片在画布中的显示区域和缩放比例"""
        if not self.original_pixmap:
            return QRectF(), 0.0

        canvas = self.contentsRect()
        pw, ph = self.original_pixmap.width(), self.original_pixmap.height()
        if pw == 0 or ph == 0:
            return QRectF(), 0.0

        # 基础缩放比例（适应画布）
        base_scale = min(canvas.width() / pw, canvas.height() / ph)
        # 应用用户缩放
        scale = base_scale * self.zoom_factor
        sw, sh = pw * scale, ph * scale

        # 应用平移偏移
        offset_x = (canvas.width() - sw) / 2 + self.pan_offset.x()
        offset_y = (canvas.height() - sh) / 2 + self.pan_offset.y()

        return QRectF(offset_x, offset_y, sw, sh), scale

    def _display_to_norm(self, pos):
        rect, _ = self._get_image_rect()
        if not rect.contains(pos):
            return None
        x = (pos.x() - rect.x()) / rect.width()
        y = (pos.y() - rect.y()) / rect.height()
        return QPointF(max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def _norm_rect_to_display(self, cx, cy, w, h):
        rect, _ = self._get_image_rect()
        x1 = rect.x() + (cx - w / 2) * rect.width()
        y1 = rect.y() + (cy - h / 2) * rect.height()
        x2 = rect.x() + (cx + w / 2) * rect.width()
        y2 = rect.y() + (cy + h / 2) * rect.height()
        return x1, y1, x2, y2

    def load_image(self, image_path):
        self.original_pixmap = QPixmap(str(image_path))
        self.annotations.clear()
        # 重置缩放和平移
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        if self.original_pixmap.isNull():
            return False
        self.update()
        return True

    # ----------------- 鼠标事件 -----------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_drawing_mode:
                # 标注模式：开始绘制边界框
                norm = self._display_to_norm(event.pos())
                if norm:
                    self.is_drawing = True
                    self.start_pos = self.current_pos = norm
            else:
                # 平移模式：开始平移
                self.is_panning = True
                self.pan_start_pos = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.MiddleButton:  # 中键重置视图
            self.zoom_factor = 1.0
            self.pan_offset = QPointF(0, 0)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        rect, _ = self._get_image_rect()

        # 更新鼠标位置用于绘制十字准星
        self.current_mouse_pos = event.pos()

        if self.is_panning:
            # 平移操作
            delta = event.pos() - self.pan_start_pos
            self.pan_start_pos = event.pos()
            self.pan_offset += delta
            self.update()
        elif self.is_drawing:
            norm = self._display_to_norm(event.pos())
            if norm:
                self.current_pos = norm
                self.update()
        else:
            # 设置光标样式
            if rect.contains(event.pos()):
                if self.is_drawing_mode:
                    # 标注模式下隐藏系统光标，我们自己绘制十字准星
                    self.setCursor(Qt.CursorShape.BlankCursor)
                else:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        # 在标注模式下，只要有鼠标移动就重绘以更新十字准星
        if self.is_drawing_mode:
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.is_panning:
            self.is_panning = False
            # 释放后根据模式设置光标
            rect, _ = self._get_image_rect()
            if rect.contains(event.pos()):
                if self.is_drawing_mode:
                    self.setCursor(Qt.BlankCursor)
                else:
                    self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        elif event.button() == Qt.LeftButton and self.is_drawing:
            # 标注完成
            end = self._display_to_norm(event.pos())
            if end and (abs(self.start_pos.x() - end.x()) > 0.003 or abs(self.start_pos.y() - end.y()) > 0.003):
                cx = (self.start_pos.x() + end.x()) / 2
                cy = (self.start_pos.y() + end.y()) / 2
                w = abs(self.start_pos.x() - end.x())
                h = abs(self.start_pos.y() - end.y())
                bbox = [self.current_class_id, cx, cy, w, h]
                self.annotations.append(bbox)
                self.bboxDrawn.emit(bbox)

            # 标注完成后自动切换回平移模式
            self.is_drawing_mode = False
            self.is_drawing = False

            # 更新光标
            rect, _ = self._get_image_rect()
            if rect.contains(event.pos()):
                self.setCursor(Qt.OpenHandCursor)

            self.update()

    # ----------------- 滚轮事件：缩放 -----------------
    def wheelEvent(self, event: QWheelEvent):
        if not self.original_pixmap:
            return

        # 1. 获取当前鼠标位置（兼容 PyQt5/6）
        pos = event.position() if hasattr(event, "position") else event.pos()
        mouse_x = pos.x()
        mouse_y = pos.y()

        # 2. 当前图片显示矩形
        old_rect, _ = self._get_image_rect()
        if old_rect.isEmpty():
            return

        # 3. 计算鼠标在图片上的相对位置 [0, 1]，并限制在边界内防止跳变
        rel_x = (mouse_x - old_rect.left()) / old_rect.width()
        rel_y = (mouse_y - old_rect.top()) / old_rect.height()
        rel_x = max(0.0, min(1.0, rel_x))
        rel_y = max(0.0, min(1.0, rel_y))

        # 4. 计算新缩放因子（推荐乘性缩放，更自然）
        delta = event.angleDelta().y()
        if delta == 0:
            return

        # 乘性缩放
        # factor = 1.25 if delta > 0 else 0.8  # 每次放大25%，缩小20%
        factor = math.pow(1.0015, delta)  # 超平滑指数方式（可选）

        new_zoom = self.zoom_factor * factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if abs(new_zoom - self.zoom_factor) < 1e-8:  # 已达边界
            return

        # 5. 正式更新缩放
        old_zoom = self.zoom_factor
        self.zoom_factor = new_zoom

        # 6. 计算新矩形
        new_rect, _ = self._get_image_rect()

        # 7. 核心：计算为了让鼠标下的图像点不动，需要调整多少平移
        # 公式：new_left = mouse_x - rel_x * new_width
        desired_left = mouse_x - rel_x * new_rect.width()
        desired_top = mouse_y - rel_y * new_rect.height()

        # 当前新矩形实际左上角位置
        actual_left = new_rect.left()
        actual_top = new_rect.top()

        # 需要额外增加的偏移量
        delta_x = desired_left - actual_left
        delta_y = desired_top - actual_top

        self.pan_offset += QPointF(delta_x, delta_y)

        # 8. 重绘
        self.update()
        event.accept()

    # ----------------- 绘制 -----------------
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.original_pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect, _ = self._get_image_rect()
        painter.drawPixmap(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()), self.original_pixmap)

        # 绘制模式信息和缩放比例
        mode_text = "标注模式" if self.is_drawing_mode else "平移模式"
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(10, 20, f"模式: {mode_text}")

        if self.zoom_factor != 1.0:
            painter.drawText(10, 40, f"缩放: {self.zoom_factor:.1f}x")
            if self.pan_offset.x() != 0 or self.pan_offset.y() != 0:
                painter.drawText(10, 60, "平移中...")

        # 已标注框
        for i, ann in enumerate(self.annotations):
            cid, cx, cy, w, h = ann
            x1, y1, x2, y2 = self._norm_rect_to_display(cx, cy, w, h)

            # 边框颜色（按类别循环）
            color = QColor(*self.colors[cid % len(self.colors)])
            pen = QPen(color, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))

            # 获取类别名
            if hasattr(self.parent(), "classes") and cid < len(self.parent().classes):
                label = self.parent().classes[cid]
            else:
                label = f"class_{cid}"

            # 标签文字（白色粗体）
            painter.setPen(Qt.white)
            painter.setFont(QApplication.font())
            painter.drawText(int(x1 + 8), int(y1 - 8), label)

        # 正在绘制的框
        if self.is_drawing:
            painter.setPen(self.drawing_pen)
            x1 = rect.x() + min(self.start_pos.x(), self.current_pos.x()) * rect.width()
            y1 = rect.y() + min(self.start_pos.y(), self.current_pos.y()) * rect.height()
            w = abs(self.start_pos.x() - self.current_pos.x()) * rect.width()
            h = abs(self.start_pos.y() - self.current_pos.y()) * rect.height()
            painter.drawRect(QRectF(x1, y1, w, h))

        # 在标注模式下绘制完整的十字准星
        if self.is_drawing_mode and rect.contains(self.current_mouse_pos):
            painter.setPen(self.crosshair_pen)
            x, y = self.current_mouse_pos.x(), self.current_mouse_pos.y()

            # 绘制水平线 - 从左到右贯穿整个画布
            painter.drawLine(0, y, self.width(), y)

            # 绘制垂直线 - 从上到下贯穿整个画布
            painter.drawLine(x, 0, x, self.height())

            # 在十字中心绘制一个小圆点
            painter.setBrush(QColor(255, 255, 255, 200))
            painter.drawEllipse(QPointF(x, y), 2, 2)

    # ----------------- 工具函数 -----------------
    def clear_annotations(self):
        self.annotations.clear()
        self.update()

    def pop_annotations(self):
        if self.annotations:
            self.annotations.pop()
            self.update()

    def set_annotations(self, detections, class_names):
        """模型检测结果直接加入（归一化）"""
        w = self.original_pixmap.width()
        h = self.original_pixmap.height()
        for det in detections:
            box = det["box"]
            name = det["class_name"]
            if name not in class_names:
                continue
            cid = class_names.index(name)
            cx = ((box[0] + box[2]) / 2) / w
            cy = ((box[1] + box[3]) / 2) / h
            bw = (box[2] - box[0]) / w
            bh = (box[3] - box[1]) / h
            self.annotations.append([cid, cx, cy, bw, bh])
            self.bboxDrawn.emit([cid, cx, cy, bw, bh])
        self.update()

    def list_annotations(self):
        return self.annotations.copy()

    def append_annotations(self, annotations):
        for a in annotations:
            self.annotations.append(a)
            self.bboxDrawn.emit(a)
        self.update()

    def reset_view(self):
        """重置视图到原始大小和位置"""
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self.update()

    def toggle_drawing_mode(self):
        """切换标注/平移模式"""
        self.is_drawing_mode = not self.is_drawing_mode

        # 更新光标
        rect, _ = self._get_image_rect()
        if rect.contains(self.mapFromGlobal(QCursor.pos())):
            if self.is_drawing_mode:
                self.setCursor(Qt.BlankCursor)  # 隐藏系统光标，使用自定义十字准星
            else:
                self.setCursor(Qt.OpenHandCursor)

        self.update()
        return self.is_drawing_mode


class AnnotationWidget(QWidget):
    def __init__(self, objectName: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(objectName)
        self.setFocusPolicy(Qt.StrongFocus)  # 接收键盘事件

        self.current_image_path = None
        self.image_files = []
        self.current_index = 0
        self.classes = ["ui_quit", "ui_menu", "ui_lv", "ui_task", "ui_bag", "ui_chat", "ui_map"]  # 根据你的游戏自行修改

        self._setup_ui()
        self._set_connections()

        StyleSheet.ANNOTATION_WIDGET.apply(self)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # ============= 左侧：画布 =============
        left = QVBoxLayout()
        self.canvas = AnnotationCanvas(self)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)  # 减少按钮间距

        # 导航控制（核心功能）
        self.prev_btn = PushButton("← 上一张")
        self.next_btn = PushButton("下一张→")
        self.prev_btn.setFixedWidth(80)
        self.next_btn.setFixedWidth(80)

        # 标注工具 - 使用下拉菜单整合
        self.tools_combo = ComboBox()
        self.tools_combo.setFixedWidth(120)
        self.tools_combo.addItems(["标注工具 ▼", "自动检测", "撤销标注", "清空标注"])
        self.tools_combo.setCurrentIndex(0)

        # 模式切换按钮
        self.mode_btn = PushButton("标注模式 (Q)")
        self.mode_btn.setCheckable(True)
        self.mode_btn.setChecked(False)
        self.mode_btn.setFixedWidth(100)

        # 缩放控制按钮
        zoom_layout = QHBoxLayout()
        zoom_layout.setSpacing(2)
        self.zoom_out_btn = PushButton("−")  # 使用减号符号，更紧凑
        self.zoom_reset_btn = PushButton("↺")  # 使用重置符号
        self.zoom_in_btn = PushButton("+")

        zoom_layout.addWidget(self.zoom_out_btn)
        zoom_layout.addWidget(self.zoom_reset_btn)
        zoom_layout.addWidget(self.zoom_in_btn)

        toolbar.addWidget(self.prev_btn)
        toolbar.addWidget(self.next_btn)
        toolbar.addWidget(self.tools_combo)
        toolbar.addWidget(self.mode_btn)
        toolbar.addLayout(zoom_layout)
        toolbar.addStretch()

        info = QHBoxLayout()
        self.image_label = BodyLabel("未加载")
        self.progress_label = CaptionLabel("0/0")

        # 添加页码跳转功能
        jump_layout = QHBoxLayout()
        jump_layout.setSpacing(4)
        self.page_edit = LineEdit()
        self.page_edit.setPlaceholderText("跳转页码")
        self.page_edit.setFixedWidth(80)
        self.jump_btn = PushButton("跳转")
        jump_layout.addWidget(CaptionLabel("跳转:"))
        jump_layout.addWidget(self.page_edit)
        jump_layout.addWidget(self.jump_btn)
        jump_layout.addStretch()

        info.addWidget(self.image_label)
        info.addStretch()
        info.addLayout(jump_layout)  # 将跳转布局添加到info布局中
        info.addWidget(self.progress_label)

        left.addLayout(info)
        left.addWidget(self.canvas, 1)
        left.addLayout(toolbar)

        # ============= 右侧：控制面板 =============
        right = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setMaximumWidth(320)
        right_layout = QVBoxLayout(right_widget)

        # 加载数据集
        g1 = QGroupBox("数据集")
        l1 = QVBoxLayout(g1)
        self.load_btn = PrimaryPushButton("加载图片文件夹")
        self.path_label = CaptionLabel("未选择")
        l1.addWidget(self.load_btn)
        l1.addWidget(self.path_label)
        right_layout.addWidget(g1)

        # 类别
        g2 = QGroupBox("类别")
        l2 = QVBoxLayout(g2)
        self.class_list = QListWidget()
        self.class_list.addItems(self.classes)
        self.class_list.setCurrentRow(0)
        l2.addWidget(self.class_list)

        add_layout = QHBoxLayout()
        self.class_edit = LineEdit()
        self.class_edit.setPlaceholderText("新类别")
        self.add_class_btn = PushButton("添加")
        add_layout.addWidget(self.class_edit)
        add_layout.addWidget(self.add_class_btn)
        l2.addLayout(add_layout)
        right_layout.addWidget(g2)

        # 当前标注列表
        g3 = QGroupBox("当前标注")
        l3 = QVBoxLayout(g3)
        self.annotation_list = QListWidget()
        l3.addWidget(self.annotation_list)
        right_layout.addWidget(g3)

        # 导出
        g4 = QGroupBox("导出")
        l4 = QVBoxLayout(g4)
        self.auto_save = CheckBox("自动保存标注")
        self.auto_save.setChecked(True)
        self.export_btn = PrimaryPushButton("导出 YOLO 格式 (Ctrl+S)")
        self.organize_btn = PushButton("整理数据集")
        l4.addWidget(self.auto_save)
        l4.addWidget(self.export_btn)
        l4.addWidget(self.organize_btn)
        right_layout.addWidget(g4)
        right_layout.addStretch()

        right.addWidget(right_widget)

        # 主布局
        main_layout.addLayout(left, 1)
        main_layout.addLayout(right)

    def _set_connections(self):
        self.load_btn.clicked.connect(self._load_dataset)
        self.prev_btn.clicked.connect(self._prev_image)
        self.next_btn.clicked.connect(self._next_image)
        self.export_btn.clicked.connect(self._export_yolo)
        self.organize_btn.clicked.connect(self._organize_dataset)
        self.add_class_btn.clicked.connect(self._add_class)
        self.tools_combo.currentTextChanged.connect(self._on_tool_selected)

        # 模式切换连接
        self.mode_btn.clicked.connect(self._toggle_drawing_mode)

        # 缩放控制连接
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_reset_btn.clicked.connect(self._zoom_reset)

        self.canvas.bboxDrawn.connect(self._on_bbox_drawn)
        self.class_list.currentRowChanged.connect(lambda row: setattr(self.canvas, "current_class_id", row))

        self.jump_btn.clicked.connect(self._jump_to_page)
        self.page_edit.returnPressed.connect(self._jump_to_page)  # 按回车也可以跳转

    # ==================== 快捷键 ====================
    def keyPressEvent(self, event):
        k = event.key()
        m = event.modifiers()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._prev_image()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._next_image()
        elif k == Qt.Key.Key_E:  # 修改：E键撤销标注
            self._undo_annotation()
        elif k == Qt.Key.Key_Z and m == Qt.KeyboardModifier.ControlModifier:
            self._undo_annotation()
        elif k == Qt.Key.Key_Q and m == Qt.KeyboardModifier.ControlModifier:
            self._clear_annotations()
        elif k == Qt.Key.Key_S and m == Qt.KeyboardModifier.ControlModifier:
            self._export_yolo()
        elif k == Qt.Key.Key_Space:
            self._detect_annotations()
        # Q键切换标注模式
        elif k == Qt.Key.Key_Q:
            self._toggle_drawing_mode()
        # 缩放快捷键
        elif k == Qt.Key.Key_Equal and m == Qt.KeyboardModifier.ControlModifier:  # Ctrl++
            self._zoom_in()
        elif k == Qt.Key.Key_Minus and m == Qt.KeyboardModifier.ControlModifier:  # Ctrl+-
            self._zoom_out()
        elif k == Qt.Key.Key_R:  # R键重置视图
            self._zoom_reset()
        elif k == Qt.Key.Key_0 and m == Qt.KeyboardModifier.ControlModifier:  # Ctrl+0
            self._zoom_reset()
        # W S 控制类别选择
        elif k == Qt.Key.Key_W:
            current_row = self.class_list.currentRow()
            new_row = current_row - 1 if current_row > 0 else self.class_list.count() - 1
            self.class_list.setCurrentRow(new_row)
        elif k == Qt.Key.Key_S:
            current_row = self.class_list.currentRow()
            new_row = current_row + 1 if current_row < self.class_list.count() - 1 else 0
            self.class_list.setCurrentRow(new_row)
        # C 复制上一次标注框
        elif k == Qt.Key.Key_C:
            self.annotation_temp = self.canvas.list_annotations()
            InfoBar.success("复制成功", f"一共复制{len(self.annotation_temp)}个标注框", parent=self)
        # V 粘贴标注框
        elif k == Qt.Key.Key_V:
            if hasattr(self, "annotation_temp") and len(self.annotation_temp) > 0:
                self.canvas.append_annotations(self.annotation_temp)
            InfoBar.success("粘贴成功", f"一共粘贴{len(self.annotation_temp)}个标注框", parent=self)
        else:
            super().keyPressEvent(event)

    # ==================== 核心功能 ====================
    def _on_tool_selected(self, tool_name):
        """处理工具下拉菜单选择"""
        if tool_name == "自动检测":
            self._detect_annotations()
        elif tool_name == "撤销标注":
            self._undo_annotation()
        elif tool_name == "清空标注":
            self._clear_annotations()

        # 重置下拉菜单到默认状态
        self.tools_combo.setCurrentIndex(0)

    def _load_dataset(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        self.dataset_path = Path(folder)
        self.path_label.setText(str(self.dataset_path))

        # 加载 classes.txt
        cp = self.dataset_path / "classes.txt"
        if cp.exists():
            with open(cp, "r", encoding="utf-8") as f:
                self.classes = [l.strip() for l in f if l.strip()]
                self.class_list.clear()
                self.class_list.addItems(self.classes)

        self.image_files = sorted(
            [p for p in self.dataset_path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}]
        )
        if self.image_files:
            self.current_index = 0
            self._load_current_image()
            InfoBar.success("成功", f"加载 {len(self.image_files)} 张图片", parent=self)

    def _load_current_image(self):
        if not self.image_files:
            return
        path = self.image_files[self.current_index]
        self.current_image_path = path
        self.image_label.setText(path.name)
        self.progress_label.setText(f"{self.current_index+1}/{len(self.image_files)}")
        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < len(self.image_files) - 1)

        self.canvas.load_image(path)
        self.annotation_list.clear()
        self._load_existing_annotations()

    def _load_existing_annotations(self):
        txt = self.current_image_path.with_suffix(".txt")
        if txt.exists():
            with open(txt, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        cid = int(parts[0])
                        vals = list(map(float, parts[1:]))
                        self.canvas.annotations.append([cid] + vals)
                        name = self.classes[cid] if cid < len(self.classes) else "unknown"
                        self.annotation_list.addItem(f"{name} {vals}")
            self.canvas.update()

    def _on_bbox_drawn(self, bbox):
        cid = bbox[0]
        name = self.classes[cid] if cid < len(self.classes) else str(cid)
        self.annotation_list.addItem(f"{name} {bbox[1:]}")

    def _prev_image(self):
        if self.auto_save.isChecked():
            self._export_yolo()
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()

    def _next_image(self):
        if self.auto_save.isChecked():
            self._export_yolo()
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self._load_current_image()

    def _clear_annotations(self):
        self.canvas.clear_annotations()
        self.annotation_list.clear()

    def _undo_annotation(self):
        self.canvas.pop_annotations()
        if self.annotation_list.count() > 0:
            self.annotation_list.takeItem(self.annotation_list.count() - 1)

    def _detect_annotations(self):
        if not hasattr(self, "detector"):
            model_path = MODULES_DIR / "best.onnx"
            if not model_path.exists():
                InfoBar.warning("未找到模型", f"{model_path} 不存在", parent=self)
                return
            self.detector = YOLOONNXDetector(
                str(model_path), class_names=self.classes, conf_threshold=0.8, input_size=(640, 640)
            )

        try:
            _, detections, _ = self.detector.detect(str(self.current_image_path))
            self.canvas.set_annotations(detections, self.classes)
            InfoBar.success("自动标注完成", f"检测到 {len(detections)} 个目标", parent=self)
        except Exception as e:
            InfoBar.error("检测失败", str(e), parent=self)

    def _add_class(self):
        name = self.class_edit.text().strip()
        if name and name not in self.classes:
            self.classes.append(name)
            self.class_list.addItem(name)
            self.class_edit.clear()

    def _export_yolo(self):
        if not self.current_image_path:
            return
        txt_path = self.current_image_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            for ann in self.canvas.annotations:
                f.write(f"{ann[0]} {ann[1]:.6f} {ann[2]:.6f} {ann[3]:.6f} {ann[4]:.6f}\n")

        # 保存 classes.txt
        with open(self.dataset_path / "classes.txt", "w", encoding="utf-8") as f:
            for c in self.classes:
                f.write(c + "\n")

    def _jump_to_page(self):
        """跳转到指定页码"""
        if not self.image_files:
            return

        try:
            page_num = int(self.page_edit.text().strip())
            if 1 <= page_num <= len(self.image_files):
                # 自动保存当前标注
                if self.auto_save.isChecked():
                    self._export_yolo()

                self.current_index = page_num - 1
                self._load_current_image()

                # 清空输入框
                self.page_edit.clear()

                InfoBar.success("跳转成功", f"已跳转到第 {page_num} 页", duration=1000, parent=self)
            else:
                InfoBar.warning("页码无效", f"请输入 1-{len(self.image_files)} 之间的数字", parent=self)
        except ValueError:
            InfoBar.warning("输入错误", "请输入有效的页码数字", parent=self)

    # ==================== 模式切换功能 ====================
    def _toggle_drawing_mode(self):
        """切换标注/平移模式"""
        is_drawing_mode = self.canvas.toggle_drawing_mode()
        self.mode_btn.setChecked(is_drawing_mode)

        # 显示模式切换提示
        mode_name = "标注模式" if is_drawing_mode else "平移模式"
        InfoBar.info("模式切换", f"已切换到 {mode_name}", duration=1000, parent=self)

    # ==================== 缩放功能 ====================
    def _zoom_in(self):
        """放大"""
        self.canvas.zoom_factor = min(self.canvas.max_zoom, self.canvas.zoom_factor + self.canvas.zoom_step)
        self.canvas.update()

    def _zoom_out(self):
        """缩小"""
        self.canvas.zoom_factor = max(self.canvas.min_zoom, self.canvas.zoom_factor - self.canvas.zoom_step)
        self.canvas.update()

    def _zoom_reset(self):
        """重置视图"""
        self.canvas.reset_view()

    # ==================== 原有功能保持不变 ====================
    def _organize_dataset(self):
        """整理数据集"""
        if not hasattr(self, "dataset_path"):
            InfoBar.warning(title="警告", content="请先加载数据集", parent=self)
            return

        # 显示配置对话框
        dialog = self._setup_organize_dialog()
        if dialog.exec_() != QDialog.Accepted:
            return

        # 选择输出目录
        output_dir = QFileDialog.getExistingDirectory(
            self, "选择输出目录", str(self.dataset_path.parent), options=QFileDialog.ShowDirsOnly
        )

        if output_dir:
            # 执行整理
            success = self.organize_yolo_dataset(
                output_dir=output_dir,
                train_ratio=self.train_ratio_spin.value(),
                cleanup_existing=self.cleanup_check.isChecked(),
                filter_annotated=self.filter_check.isChecked(),
                shuffle_images=self.shuffle_check.isChecked(),
            )

    def organize_yolo_dataset(
        self, output_dir, train_ratio=0.8, cleanup_existing=True, filter_annotated=True, shuffle_images=True
    ):
        """整理为 YOLO 训练集格式 - 增强版本

        Args:
            output_dir: 输出目录
            train_ratio: 训练集比例
            cleanup_existing: 是否清理已存在的输出目录
            filter_annotated: 是否只筛选有标注的图片
            shuffle_images: 是否随机打乱图片顺序
        """
        if not hasattr(self, "dataset_path"):
            InfoBar.warning(title="警告", content="请先加载数据集", parent=self)
            return False

        output_path = Path(output_dir)

        # 清理已存在的输出目录
        if cleanup_existing and output_path.exists():
            try:
                shutil.rmtree(output_path)
                log.info(f"已清理现有目录: {output_path}")
            except Exception as e:
                log.error(f"清理目录失败: {e}")
                InfoBar.error(title="错误", content=f"清理目录失败: {e}", parent=self)
                return False

        # 创建标准 YOLO 目录结构
        directories = ["images/train", "images/val", "labels/train", "labels/val"]

        for directory in directories:
            (output_path / directory).mkdir(parents=True, exist_ok=True)

        # 筛选有标注的图片
        annotated_images = []
        for image_path in self.image_files:
            txt_path = image_path.with_suffix(".txt")

            if filter_annotated:
                # 只选择有标注文件的图片
                if txt_path.exists() and txt_path.stat().st_size > 0:
                    annotated_images.append(image_path)
            else:
                # 包含所有图片
                annotated_images.append(image_path)

        if not annotated_images:
            InfoBar.warning(
                title="警告", content="未找到有标注的图片" if filter_annotated else "未找到图片", parent=self
            )
            return False

        # 随机打乱图片顺序
        if shuffle_images:
            import random

            random.shuffle(annotated_images)
            log.info("已随机打乱图片顺序")
        else:
            # 按文件名排序确保一致性
            annotated_images.sort(key=lambda x: x.name.lower())

        # 分割训练集和验证集
        total_count = len(annotated_images)
        train_count = int(total_count * train_ratio)

        train_images = annotated_images[:train_count]
        val_images = annotated_images[train_count:]

        success_count = 0
        failed_count = 0

        # 处理训练集
        for image_path in train_images:
            if self._copy_image_and_label(image_path, output_path, "train"):
                success_count += 1
            else:
                failed_count += 1

        # 处理验证集
        for image_path in val_images:
            if self._copy_image_and_label(image_path, output_path, "val"):
                success_count += 1
            else:
                failed_count += 1

        # 创建 dataset.yaml 配置文件
        self._create_yolo_config(output_path, output_path.name)

        # 创建类别文件
        self._create_classes_file(output_path)

        # 生成数据集统计信息
        stats = self._generate_dataset_stats(output_path, len(train_images), len(val_images))

        # 显示结果
        if failed_count == 0:
            InfoBar.success(
                title="整理完成",
                content=f"成功整理 {success_count} 个样本 ({len(train_images)}训练/{len(val_images)}验证)\n{stats}",
                parent=self,
            )
        else:
            InfoBar.warning(
                title="部分完成", content=f"成功: {success_count}, 失败: {failed_count}\n{stats}", parent=self
            )

        return failed_count == 0

    def _copy_image_and_label(self, image_path, output_path, split):
        """复制图片和标注文件到指定分割集"""
        try:
            # 复制图片文件
            image_dest = output_path / "images" / split / image_path.name
            shutil.copy2(image_path, image_dest)

            # 复制对应的标注文件
            txt_src = image_path.with_suffix(".txt")
            if txt_src.exists() and txt_src.stat().st_size > 0:
                txt_dest = output_path / "labels" / split / txt_src.name
                shutil.copy2(txt_src, txt_dest)
            else:
                # 如果没有标注文件，创建一个空的
                txt_dest = output_path / "labels" / split / txt_src.name
                txt_dest.touch()

            return True

        except Exception as e:
            log.error(f"复制文件失败 {image_path}: {e}")
            return False

    def _create_classes_file(self, output_path):
        """创建类别文件"""
        classes_file = output_path / "classes.txt"
        try:
            with open(classes_file, "w", encoding="utf-8") as f:
                for class_name in self.classes:
                    f.write(f"{class_name}\n")
            log.info(f"已创建类别文件: {classes_file}")
        except Exception as e:
            log.error(f"创建类别文件失败: {e}")

    def _generate_dataset_stats(self, dataset_path, train_count, val_count):
        """生成数据集统计信息"""
        total_count = train_count + val_count
        train_annotations = 0
        val_annotations = 0

        # 统计训练集标注数量
        train_labels_dir = dataset_path / "labels" / "train"
        if train_labels_dir.exists():
            for txt_file in train_labels_dir.glob("*.txt"):
                if txt_file.stat().st_size > 0:
                    train_annotations += 1

        # 统计验证集标注数量
        val_labels_dir = dataset_path / "labels" / "val"
        if val_labels_dir.exists():
            for txt_file in val_labels_dir.glob("*.txt"):
                if txt_file.stat().st_size > 0:
                    val_annotations += 1

        stats = f"""
    数据集统计:
    - 总样本数: {total_count}
    - 训练集: {train_count} (有标注: {train_annotations})
    - 验证集: {val_count} (有标注: {val_annotations})
    - 类别数: {len(self.classes)}
    - 标注率: {(train_annotations + val_annotations) / total_count * 100:.1f}%
    """
        return stats

    def _create_yolo_config(self, output_path, dataset_name):
        """创建 YOLO 数据集配置文件"""
        # 获取绝对路径
        abs_path = output_path.absolute()

        config_content = f"""# YOLO 数据集配置文件
    # 数据集路径
    path: {abs_path}  # 数据集根目录
    train: images/train  # 训练图片目录
    val: images/val      # 验证图片目录
    test:                # 测试集目录（可选）

    # 类别数量
    nc: {len(self.classes)}

    # 类别名称
    names: {self.classes}

    # 数据集信息
    # 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    # 总类别: {len(self.classes)}
    # 类别列表: {', '.join(self.classes)}
    """

        config_file = output_path / f"{dataset_name}.yaml"
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(config_content)
            log.info(f"已创建配置文件: {config_file}")
        except Exception as e:
            log.error(f"创建配置文件失败: {e}")

    def _setup_organize_dialog(self):
        """创建数据集整理配置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("YOLO 数据集配置")
        dialog.setMinimumWidth(400)

        layout = QFormLayout(dialog)

        # 训练集比例
        self.train_ratio_spin = DoubleSpinBox()
        self.train_ratio_spin.setRange(0.1, 0.9)
        self.train_ratio_spin.setValue(0.8)
        self.train_ratio_spin.setSingleStep(0.1)
        layout.addRow("训练集比例:", self.train_ratio_spin)

        # 清理选项
        self.cleanup_check = CheckBox("清理已存在的输出目录")
        self.cleanup_check.setChecked(True)
        layout.addRow(self.cleanup_check)

        # 筛选选项
        self.filter_check = CheckBox("只导出有标注的图片")
        self.filter_check.setChecked(True)
        layout.addRow(self.filter_check)

        # 随机打乱选项
        self.shuffle_check = CheckBox("随机打乱图片顺序")
        self.shuffle_check.setChecked(True)
        layout.addRow(self.shuffle_check)

        # 统计信息
        total_images = len(self.image_files)
        annotated_images = len([img for img in self.image_files if img.with_suffix(".txt").exists()])

        stats_label = CaptionLabel(
            f"当前数据集: {total_images} 张图片, {annotated_images} 张有标注 ({annotated_images/total_images*100:.1f}%)"
        )
        layout.addRow("统计:", stats_label)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)

        return dialog
