"""
通用图像查看器组件

统一三个窗口的图像展示功能，支持可配置的功能启用/禁用。
功能包括：缩放、平移、标注、区域选择、远程控制、操作录制等。
"""

from enum import Flag, auto, Enum
from typing import Optional, List, Dict, Any

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QCursor, QWheelEvent, QMouseEvent
from PyQt5.QtWidgets import QLabel

from src.vstain.utils.logger import get_logger

log = get_logger()


# ==================== 枚举定义 ====================

class ImageFeature(Flag):
    """
    图像功能枚举（位标志，支持组合）

    使用示例：
        viewer.set_features(ImageFeature.ZOOM | ImageFeature.PAN)
        viewer.set_features(ImageFeature.ANNOTATION_MODE)
    """
    NONE = 0
    ZOOM = auto()           # 缩放功能
    PAN = auto()            # 平移功能
    ANNOTATION = auto()     # 标注功能
    SELECTION = auto()      # 区域选择功能
    REMOTE_CONTROL = auto()  # 远程控制功能
    RECORDING = auto()      # 操作录制功能
    CROSSHAIR = auto()      # 十字准星
    INFO_OVERLAY = auto()   # 信息叠加层

    # 预定义组合
    BASIC = ZOOM | PAN                               # 基础功能
    ANNOTATION_MODE = BASIC | ANNOTATION | CROSSHAIR  # 标注模式
    CAPTURE_MODE = SELECTION                         # 捕获模式
    REMOTE_MODE = BASIC | REMOTE_CONTROL | RECORDING  # 远程控制模式


class InteractionMode(Enum):
    """交互模式枚举"""
    VIEW = "view"           # 纯查看模式
    PAN = "pan"            # 平移模式
    ANNOTATE = "annotate"  # 标注模式
    SELECT = "select"      # 选择模式
    REMOTE = "remote"      # 远程控制模式


class CoordinateSystem(Enum):
    """坐标系统枚举"""
    NORMALIZED = "normalized"  # 归一化坐标 [0, 1]
    ABSOLUTE = "absolute"      # 绝对像素坐标


# ==================== 主组件 ====================

class UniversalImageViewer(QLabel):
    """
    通用图像查看器组件

    功能特性：
    - 可配置的功能启用/禁用
    - 信号驱动的事件通知
    - 多种交互模式支持
    - 坐标系统转换

    使用示例：
        viewer = UniversalImageViewer()
        viewer.set_features(ImageFeature.ANNOTATION_MODE)
        viewer.set_mode(InteractionMode.ANNOTATE)
        viewer.imageClicked.connect(on_image_click)
    """

    # ==================== 信号定义 ====================

    # 图像相关信号
    imageLoaded = pyqtSignal(QPixmap)                    # 图像加载完成
    imageChanged = pyqtSignal()                          # 图像内容改变

    # 缩放/平移信号
    zoomChanged = pyqtSignal(float)                      # 缩放倍率改变 (scale)
    panChanged = pyqtSignal(QPointF)                     # 平移偏移改变 (offset)
    viewReset = pyqtSignal()                             # 视图重置

    # 交互信号
    modeChanged = pyqtSignal(InteractionMode)            # 交互模式改变
    imageClicked = pyqtSignal(QPointF, Qt.MouseButton)   # 图像点击 (归一化坐标, 按钮)
    imageDoubleClicked = pyqtSignal(QPointF)             # 图像双击 (归一化坐标)
    mousePositionChanged = pyqtSignal(QPointF)           # 鼠标位置改变 (归一化坐标)

    # 标注相关信号
    # 标注完成 {class_id, cx, cy, w, h}
    annotationDrawn = pyqtSignal(dict)
    annotationSelected = pyqtSignal(int)                 # 标注被选中 (索引)
    annotationsCleared = pyqtSignal()                    # 标注清空

    # 区域选择信号
    # 区域选中 {x, y, width, height}
    regionSelected = pyqtSignal(dict)
    regionCleared = pyqtSignal()                         # 区域清除

    # 远程控制信号
    remoteMouseEvent = pyqtSignal(
        str, QPointF, str)     # 远程鼠标事件 (事件类型, 坐标, 按钮)
    remoteKeyEvent = pyqtSignal(str, int)                # 远程键盘事件 (事件类型, 键码)
    remoteScrollEvent = pyqtSignal(QPointF, int)         # 远程滚轮事件 (坐标, 滚动量)

    # 录制信号
    recordingStarted = pyqtSignal()                      # 录制开始
    recordingStopped = pyqtSignal()                      # 录制停止
    operationRecorded = pyqtSignal(dict)                 # 操作已录制

    def __init__(self, parent=None):
        super().__init__(parent)

        # ==================== 基础配置 ====================
        self._features = ImageFeature.NONE
        self._mode = InteractionMode.VIEW
        self._coordinate_system = CoordinateSystem.NORMALIZED

        # ==================== 图像数据 ====================
        self._pixmap: Optional[QPixmap] = None
        self._image_path: Optional[str] = None

        # ==================== 缩放/平移 ====================
        self._zoom_factor = 1.0
        self._min_zoom = 0.01
        self._max_zoom = 10.0
        self._zoom_step = 0.1
        self._pan_offset = QPointF(0, 0)

        # ==================== 交互状态 ====================
        self._is_panning = False
        self._is_drawing = False
        self._is_selecting = False
        self._pan_start_pos: Optional[QPointF] = None
        self._draw_start_pos: Optional[QPointF] = None
        self._draw_current_pos: Optional[QPointF] = None
        self._select_start_pos: Optional[QPointF] = None
        self._select_end_pos: Optional[QPointF] = None
        self._current_mouse_pos = QPointF()

        # ==================== 标注数据 ====================
        self._annotations: List[Dict] = []  # [{class_id, cx, cy, w, h}]
        self._current_class_id = 0
        self._selected_annotation = -1

        # ==================== 选区数据 ====================
        self._selected_region: Optional[Dict] = None  # {x, y, width, height}

        # ==================== 远程控制 ====================
        self._remote_target = None  # 远程控制目标（hwnd等）
        self._is_recording = False
        self._operation_recorder = None

        # ==================== UI设置 ====================
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self.setMinimumSize(400, 400)
        self._setup_style()

        # ==================== 画笔配置 ====================
        self._bbox_pen = QPen(QColor(0, 255, 0), 2)
        self._drawing_pen = QPen(
            QColor(0, 0, 255), 2, Qt.DashLine)
        self._crosshair_pen = QPen(
            QColor(255, 0, 0), 2, Qt.DashLine)
        self._selection_pen = QPen(
            QColor(255, 0, 0), 2, Qt.SolidLine)

        log.info("UniversalImageViewer initialized")

    # ==================== 公共API ====================

    def set_features(self, features: ImageFeature) -> None:
        """
        设置启用的功能

        Args:
            features: 功能标志（可组合）

        Examples:
            viewer.set_features(ImageFeature.ZOOM | ImageFeature.PAN)
            viewer.set_features(ImageFeature.ANNOTATION_MODE)
        """
        self._features = features
        self._update_cursor()
        log.debug(f"Features set to: {features}")

    def enable_feature(self, feature: ImageFeature) -> None:
        """启用单个功能"""
        self._features |= feature
        self._update_cursor()
        log.debug(f"Feature enabled: {feature}")

    def disable_feature(self, feature: ImageFeature) -> None:
        """禁用单个功能"""
        self._features &= ~feature
        self._update_cursor()
        log.debug(f"Feature disabled: {feature}")

    def has_feature(self, feature: ImageFeature) -> bool:
        """检查是否启用了某功能"""
        return bool(self._features & feature)

    def set_mode(self, mode: InteractionMode) -> None:
        """
        设置交互模式

        Args:
            mode: 交互模式
        """
        if self._mode != mode:
            self._mode = mode
            self._update_cursor()
            self.modeChanged.emit(mode)
            log.debug(f"Mode changed to: {mode.value}")

    def get_mode(self) -> InteractionMode:
        """获取当前交互模式"""
        return self._mode

    @pyqtSlot(str)
    @pyqtSlot(QPixmap)
    def load_image(self, image: Any) -> bool:
        """
        加载图像

        Args:
            image: 图像路径(str) 或 QPixmap对象

        Returns:
            bool: 加载是否成功
        """
        if isinstance(image, str):
            self._image_path = image
            self._pixmap = QPixmap(image)
        elif isinstance(image, QPixmap):
            self._pixmap = image
            self._image_path = None
        else:
            log.error(f"Unsupported image type: {type(image)}")
            return False

        if self._pixmap.isNull():
            log.error("Failed to load image")
            return False

        # 重置视图
        self._zoom_factor = 1.0
        self._pan_offset = QPointF(0, 0)

        # 清空数据
        if self.has_feature(ImageFeature.ANNOTATION):
            self._annotations.clear()
        if self.has_feature(ImageFeature.SELECTION):
            self._selected_region = None

        self.update()
        self.imageLoaded.emit(self._pixmap)
        log.info(f"Image loaded: {self._image_path or 'QPixmap'}")
        return True

    def get_pixmap(self) -> Optional[QPixmap]:
        """获取当前图像"""
        return self._pixmap

    # ==================== 缩放/平移控制 ====================

    @pyqtSlot()
    def zoom_in(self) -> None:
        """放大"""
        if self.has_feature(ImageFeature.ZOOM):
            self._zoom_factor = min(
                self._max_zoom, self._zoom_factor + self._zoom_step)
            self.update()
            self.zoomChanged.emit(self._zoom_factor)

    @pyqtSlot()
    def zoom_out(self) -> None:
        """缩小"""
        if self.has_feature(ImageFeature.ZOOM):
            self._zoom_factor = max(
                self._min_zoom, self._zoom_factor - self._zoom_step)
            self.update()
            self.zoomChanged.emit(self._zoom_factor)

    @pyqtSlot()
    def reset_view(self) -> None:
        """重置视图"""
        self._zoom_factor = 1.0
        self._pan_offset = QPointF(0, 0)
        self.update()
        self.viewReset.emit()
        self.zoomChanged.emit(self._zoom_factor)
        self.panChanged.emit(self._pan_offset)
        log.debug("View reset")

    def get_zoom_factor(self) -> float:
        """获取缩放倍率"""
        return self._zoom_factor

    def set_zoom_factor(self, factor: float) -> None:
        """设置缩放倍率"""
        self._zoom_factor = max(self._min_zoom, min(self._max_zoom, factor))
        self.update()
        self.zoomChanged.emit(self._zoom_factor)

    # ==================== 标注控制 ====================

    @pyqtSlot(int)
    def set_current_class(self, class_id: int) -> None:
        """设置当前标注类别"""
        self._current_class_id = class_id
        log.debug(f"Current class set to: {class_id}")

    @pyqtSlot()
    def clear_annotations(self) -> None:
        """清空所有标注"""
        self._annotations.clear()
        self.update()
        self.annotationsCleared.emit()
        log.info("Annotations cleared")

    @pyqtSlot()
    def undo_annotation(self) -> None:
        """撤销最后一个标注"""
        if self._annotations:
            removed = self._annotations.pop()
            self.update()
            log.debug(f"Annotation undone: {removed}")

    def get_annotations(self) -> List[Dict]:
        """获取所有标注"""
        return self._annotations.copy()

    def add_annotation(self, annotation: Dict) -> None:
        """
        添加标注

        Args:
            annotation: {class_id, cx, cy, w, h} (归一化坐标)
        """
        self._annotations.append(annotation)
        self.update()
        self.annotationDrawn.emit(annotation)
        log.debug(f"Annotation added: {annotation}")

    # ==================== 区域选择控制 ====================

    @pyqtSlot()
    def clear_selection(self) -> None:
        """清除选择区域"""
        self._selected_region = None
        self._select_start_pos = None
        self._select_end_pos = None
        self.update()
        self.regionCleared.emit()
        log.debug("Selection cleared")

    def get_selected_region(self) -> Optional[Dict]:
        """获取选中的区域"""
        return self._selected_region

    # ==================== 远程控制 ====================

    def set_remote_target(self, target: Any) -> None:
        """设置远程控制目标"""
        self._remote_target = target
        log.debug(f"Remote target set: {target}")

    def set_operation_recorder(self, recorder: Any) -> None:
        """设置操作录制器"""
        self._operation_recorder = recorder
        log.debug("Operation recorder set")

    @pyqtSlot()
    def start_recording(self) -> None:
        """开始录制"""
        self._is_recording = True
        self.recordingStarted.emit()
        log.info("Recording started")

    @pyqtSlot()
    def stop_recording(self) -> None:
        """停止录制"""
        self._is_recording = False
        self.recordingStopped.emit()
        log.info("Recording stopped")

    # ==================== 坐标转换 ====================

    def _get_image_rect(self) -> tuple[QRectF, float]:
        """计算图像在画布中的显示区域和缩放比例"""
        if not self._pixmap:
            return QRectF(), 0.0

        canvas = self.contentsRect()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw == 0 or ph == 0:
            return QRectF(), 0.0

        # 基础缩放比例（适应画布）
        base_scale = min(canvas.width() / pw, canvas.height() / ph)
        # 应用用户缩放
        scale = base_scale * self._zoom_factor
        sw, sh = pw * scale, ph * scale

        # 应用平移偏移
        offset_x = (canvas.width() - sw) / 2 + self._pan_offset.x()
        offset_y = (canvas.height() - sh) / 2 + self._pan_offset.y()

        return QRectF(offset_x, offset_y, sw, sh), scale

    def display_to_normalized(self, pos: QPointF) -> Optional[QPointF]:
        """
        显示坐标转归一化坐标

        Args:
            pos: 显示坐标

        Returns:
            归一化坐标 [0, 1] 或 None（如果不在图像内）
        """
        rect, _ = self._get_image_rect()
        if not rect.contains(pos):
            return None

        x = (pos.x() - rect.x()) / rect.width()
        y = (pos.y() - rect.y()) / rect.height()
        return QPointF(max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def normalized_to_display(self, norm_pos: QPointF) -> QPointF:
        """归一化坐标转显示坐标"""
        rect, _ = self._get_image_rect()
        x = rect.x() + norm_pos.x() * rect.width()
        y = rect.y() + norm_pos.y() * rect.height()
        return QPointF(x, y)

    def normalized_to_absolute(self, norm_pos: QPointF) -> QPointF:
        """归一化坐标转图像绝对坐标"""
        if not self._pixmap:
            return QPointF()

        x = norm_pos.x() * self._pixmap.width()
        y = norm_pos.y() * self._pixmap.height()
        return QPointF(x, y)

    # ==================== 事件处理 ====================

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            norm_pos = self.display_to_normalized(event.pos())

            # 标注模式
            if self._mode == InteractionMode.ANNOTATE and self.has_feature(ImageFeature.ANNOTATION):
                if norm_pos:
                    self._is_drawing = True
                    self._draw_start_pos = self._draw_current_pos = norm_pos

            # 选择模式
            elif self._mode == InteractionMode.SELECT and self.has_feature(ImageFeature.SELECTION):
                self._is_selecting = True
                self._select_start_pos = event.pos()
                self._select_end_pos = event.pos()

            # 平移模式
            elif self._mode == InteractionMode.PAN and self.has_feature(ImageFeature.PAN):
                self._is_panning = True
                self._pan_start_pos = event.pos()
                self.setCursor(Qt.ClosedHandCursor)

            # 远程控制模式
            elif self._mode == InteractionMode.REMOTE and self.has_feature(ImageFeature.REMOTE_CONTROL):
                if norm_pos:
                    abs_pos = self.normalized_to_absolute(norm_pos)
                    button = "left" if event.button() == Qt.LeftButton else "right"
                    self.remoteMouseEvent.emit("press", abs_pos, button)

        elif event.button() == Qt.MiddleButton:
            # 中键重置视图
            self.reset_view()

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        self._current_mouse_pos = event.pos()
        norm_pos = self.display_to_normalized(event.pos())

        if norm_pos:
            self.mousePositionChanged.emit(norm_pos)

        # 平移
        if self._is_panning:
            delta = event.pos() - self._pan_start_pos
            self._pan_start_pos = event.pos()
            self._pan_offset += delta
            self.update()
            self.panChanged.emit(self._pan_offset)

        # 标注绘制
        elif self._is_drawing:
            if norm_pos:
                self._draw_current_pos = norm_pos
                self.update()

        # 区域选择
        elif self._is_selecting:
            self._select_end_pos = event.pos()
            self.update()

        # 远程控制
        elif self._mode == InteractionMode.REMOTE and norm_pos:
            abs_pos = self.normalized_to_absolute(norm_pos)
            self.remoteMouseEvent.emit("move", abs_pos, "")

        # 更新光标样式
        self._update_cursor()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            # 标注完成
            if self._is_drawing:
                end_pos = self.display_to_normalized(event.pos())
                if end_pos and self._draw_start_pos:
                    # 检查最小尺寸
                    if (abs(self._draw_start_pos.x() - end_pos.x()) > 2 or
                            abs(self._draw_start_pos.y() - end_pos.y()) > 2):

                        cx = (self._draw_start_pos.x() + end_pos.x()) / 2
                        cy = (self._draw_start_pos.y() + end_pos.y()) / 2
                        w = abs(self._draw_start_pos.x() - end_pos.x())
                        h = abs(self._draw_start_pos.y() - end_pos.y())

                        annotation = {
                            'class_id': self._current_class_id,
                            'cx': cx,
                            'cy': cy,
                            'w': w,
                            'h': h
                        }
                        self._annotations.append(annotation)
                        self.annotationDrawn.emit(annotation)
                        log.debug(f"Annotation drawn: {annotation}")

                self._is_drawing = False
                self._draw_start_pos = None
                self._draw_current_pos = None

            # 选择完成
            elif self._is_selecting:
                if self._select_start_pos and self._select_end_pos:
                    start_x = min(self._select_start_pos.x(),
                                  self._select_end_pos.x())
                    start_y = min(self._select_start_pos.y(),
                                  self._select_end_pos.y())
                    end_x = max(self._select_start_pos.x(),
                                self._select_end_pos.x())
                    end_y = max(self._select_start_pos.y(),
                                self._select_end_pos.y())

                    width = end_x - start_x
                    height = end_y - start_y

                    if width > 2 and height > 2:
                        self._selected_region = {
                            'x': int(start_x),
                            'y': int(start_y),
                            'width': int(width),
                            'height': int(height)
                        }
                        self.regionSelected.emit(self._selected_region)
                        log.debug(f"Region selected: {self._selected_region}")

                self._is_selecting = False

            # 平移完成
            elif self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.ArrowCursor)

        self._update_cursor()
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        """鼠标滚轮事件 - 缩放"""
        if not self.has_feature(ImageFeature.ZOOM) or not self._pixmap:
            return

        # 远程控制模式下转发滚轮事件
        if self._mode == InteractionMode.REMOTE:
            norm_pos = self.display_to_normalized(event.pos())
            if norm_pos:
                abs_pos = self.normalized_to_absolute(norm_pos)
                delta = 1 if event.angleDelta().y() > 0 else -1
                self.remoteScrollEvent.emit(abs_pos, delta)
            return

        # 以鼠标位置为中心缩放
        pos = event.position() if hasattr(event, "position") else event.pos()
        old_rect, _ = self._get_image_rect()

        if old_rect.isEmpty():
            return

        # 计算鼠标相对位置
        rel_x = (pos.x() - old_rect.left()) / old_rect.width()
        rel_y = (pos.y() - old_rect.top()) / old_rect.height()
        rel_x = max(0.0, min(1.0, rel_x))
        rel_y = max(0.0, min(1.0, rel_y))

        # 计算新缩放
        delta = event.angleDelta().y()
        if delta > 0:
            new_zoom = self._zoom_factor * 0.1
        else:
            new_zoom = self._zoom_factor * 0.1

        new_zoom = max(self._min_zoom, min(self._max_zoom, new_zoom))

        if abs(new_zoom - self._zoom_factor) < 0.01:
            return

        self._zoom_factor = new_zoom
        new_rect, _ = self._get_image_rect()

        # 调整平移以保持鼠标位置不变
        desired_left = pos.x() - rel_x * new_rect.width()
        desired_top = pos.y() - rel_y * new_rect.height()

        delta_x = desired_left - new_rect.left()
        delta_y = desired_top - new_rect.top()

        self._pan_offset += QPointF(delta_x, delta_y)

        self.update()
        self.zoomChanged.emit(self._zoom_factor)
        event.accept()

    def paintEvent(self, event):
        """绘制事件"""
        super().paintEvent(event)

        if not self._pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制图像
        rect, _ = self._get_image_rect()
        painter.drawPixmap(
            int(rect.x()), int(rect.y()),
            int(rect.width()), int(rect.height()),
            self._pixmap
        )

        # 绘制信息叠加层
        if self.has_feature(ImageFeature.INFO_OVERLAY):
            self._draw_info_overlay(painter)

        # 绘制标注
        if self.has_feature(ImageFeature.ANNOTATION):
            self._draw_annotations(painter, rect)

        # 绘制正在绘制的标注
        if self._is_drawing and self._draw_start_pos and self._draw_current_pos:
            self._draw_current_annotation(painter, rect)

        # 绘制选择区域
        if self.has_feature(ImageFeature.SELECTION):
            self._draw_selection(painter)

        # 绘制十字准星
        if self.has_feature(ImageFeature.CROSSHAIR) and self._mode == InteractionMode.ANNOTATE:
            self._draw_crosshair(painter)

    # ==================== 内部绘制方法 ====================

    def _draw_info_overlay(self, painter: QPainter):
        """绘制信息叠加层"""
        painter.setPen(Qt.white)
        y = 20

        # 模式信息
        mode_text = f"模式: {self._mode.value}"
        painter.drawText(10, y, mode_text)
        y += 20

        # 缩放信息
        if self._zoom_factor != 1.0:
            painter.drawText(10, y, f"缩放: {self._zoom_factor:.1f}x")
            y += 20

    def _draw_annotations(self, painter: QPainter, rect: QRectF):
        """绘制所有标注"""
        for i, ann in enumerate(self._annotations):
            cx, cy, w, h = ann['cx'], ann['cy'], ann['w'], ann['h']

            x1 = rect.x() + (cx - w / 2) * rect.width()
            y1 = rect.y() + (cy - h / 2) * rect.height()
            x2 = rect.x() + (cx + w / 2) * rect.width()
            y2 = rect.y() + (cy + h / 2) * rect.height()

            # 选中状态高亮
            if i == self._selected_annotation:
                painter.setPen(QPen(QColor(255, 255, 0), 3))
            else:
                # color = C.BBOX_COLORS[ann['class_id'] % len(C.BBOX_COLORS)]
                color = (0, 255, 0)
                painter.setPen(QPen(QColor(*color), 1))

            painter.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))

    def _draw_current_annotation(self, painter: QPainter, rect: QRectF):
        """绘制正在绘制的标注"""
        painter.setPen(self._drawing_pen)

        x1 = rect.x() + min(self._draw_start_pos.x(),
                            self._draw_current_pos.x()) * rect.width()
        y1 = rect.y() + min(self._draw_start_pos.y(),
                            self._draw_current_pos.y()) * rect.height()
        w = abs(self._draw_start_pos.x() -
                self._draw_current_pos.x()) * rect.width()
        h = abs(self._draw_start_pos.y() -
                self._draw_current_pos.y()) * rect.height()

        painter.drawRect(QRectF(x1, y1, w, h))

    def _draw_selection(self, painter: QPainter):
        """绘制选择区域"""
        # 正在选择
        if self._is_selecting and self._select_start_pos and self._select_end_pos:
            painter.setPen(self._selection_pen)

            start_x = min(self._select_start_pos.x(), self._select_end_pos.x())
            start_y = min(self._select_start_pos.y(), self._select_end_pos.y())
            end_x = max(self._select_start_pos.x(), self._select_end_pos.x())
            end_y = max(self._select_start_pos.y(), self._select_end_pos.y())

            painter.drawRect(start_x, start_y, end_x -
                             start_x, end_y - start_y)

        # 已选择区域
        elif self._selected_region:
            painter.setPen(
                QPen(QColor(0, 255, 0), 1))
            painter.drawRect(
                self._selected_region['x'],
                self._selected_region['y'],
                self._selected_region['width'],
                self._selected_region['height']
            )

    def _draw_crosshair(self, painter: QPainter):
        """绘制十字准星"""
        rect, _ = self._get_image_rect()
        if rect.contains(self._current_mouse_pos):
            painter.setPen(self._crosshair_pen)
            x, y = self._current_mouse_pos.x(), self._current_mouse_pos.y()

            # 水平线
            painter.drawLine(0, int(y), self.width(), int(y))
            # 垂直线
            painter.drawLine(int(x), 0, int(x), self.height())

            # 中心点
            painter.setBrush(QColor(0, 255, 0))
            painter.drawEllipse(QPointF(x, y), 2, 2)

    def _setup_style(self):
        """设置样式"""
        self.setStyleSheet(
            "background:#1e1e1e; border: 2px solid #333; border-radius: 6px;"
        )

    def _update_cursor(self):
        """更新光标样式"""
        rect, _ = self._get_image_rect()

        if not rect.contains(self.mapFromGlobal(QCursor.pos())):
            self.setCursor(Qt.ArrowCursor)
            return

        if self._mode == InteractionMode.ANNOTATE and self.has_feature(ImageFeature.CROSSHAIR):
            self.setCursor(Qt.BlankCursor)
        elif self._mode == InteractionMode.PAN:
            self.setCursor(
                Qt.OpenHandCursor if not self._is_panning else Qt.ClosedHandCursor)
        elif self._mode == InteractionMode.SELECT:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
