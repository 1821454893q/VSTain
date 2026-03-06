"""带主题的可拖拽分割条组件

通过 QSS 控制主题色，通过 pyqtProperty 暴露 grip 圆点颜色，
背景色由 QSS background-color + :hover 驱动。

用法::

    from src.vstain.components import ThemedSplitter

    # 基本用法 —— 水平分割
    splitter = ThemedSplitter(Qt.Horizontal, parent=self)
    splitter.addWidget(left_widget)
    splitter.addWidget(right_widget)
    splitter.setStretchFactor(0, 1)   # 左侧自适应
    splitter.setStretchFactor(1, 0)   # 右侧固定

    # 垂直分割
    splitter_v = ThemedSplitter(Qt.Vertical, parent=self)
    splitter_v.addWidget(top_widget)
    splitter_v.addWidget(bottom_widget)

    # 自定义手柄宽度
    splitter = ThemedSplitter(Qt.Horizontal, parent=self, handle_width=10)

QSS 自定义示例 (在对应 dark/light .qss 文件中)::

    ThemedSplitterHandle {
        background-color: #37373C;
        qproperty-gripColor: #6E6E73;
        qproperty-gripHoverColor: #78AADC;
    }
    ThemedSplitterHandle:hover {
        background-color: rgba(70, 130, 200, 60);
    }
"""

from PyQt5.QtCore import Qt, QSize, QPointF, pyqtProperty
from PyQt5.QtGui import QPainter, QColor, QBrush
from PyQt5.QtWidgets import QSplitter, QSplitterHandle, QStyle, QStyleOption

from src.vstain.common.style_sheet import StyleSheet

_DEFAULT_GRIP_COLOR = QColor(140, 140, 145)
_DEFAULT_GRIP_HOVER_COLOR = QColor(120, 170, 220)


class ThemedSplitterHandle(QSplitterHandle):
    """带 grip 圆点指示符的分割条手柄

    颜色完全由 QSS 控制:
    - ``background-color`` / ``:hover`` 控制背景
    - ``qproperty-gripColor`` 控制圆点默认色
    - ``qproperty-gripHoverColor`` 控制圆点悬停色
    """

    def __init__(self, orientation, parent, handle_width=7):
        super().__init__(orientation, parent)
        self._hovered = False
        self._handle_width = handle_width
        self._grip_color = QColor(_DEFAULT_GRIP_COLOR)
        self._grip_hover_color = QColor(_DEFAULT_GRIP_HOVER_COLOR)
        self._dot_r = 1.5
        self._rows = 5
        self._cols = 2
        self._sx = 4.0
        self._sy = 5.0
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)

    # ---- QSS 可配置属性 ----
    @pyqtProperty(QColor)
    def gripColor(self):
        return self._grip_color

    @gripColor.setter
    def gripColor(self, c: QColor):
        self._grip_color = QColor(c)
        self.update()

    @pyqtProperty(QColor)
    def gripHoverColor(self):
        return self._grip_hover_color

    @gripHoverColor.setter
    def gripHoverColor(self, c: QColor):
        self._grip_hover_color = QColor(c)
        self.update()

    # ---- 尺寸 ----
    def sizeHint(self):
        w = self._handle_width
        if self.orientation() == Qt.Horizontal:
            return QSize(w, 0)
        return QSize(0, w)

    # ---- 交互 ----
    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ---- 绘制 ----
    def paintEvent(self, event):
        p = QPainter(self)

        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)

        p.setRenderHint(QPainter.Antialiasing)
        color = self._grip_hover_color if self._hovered else self._grip_color
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        total_h = (self._rows - 1) * self._sy
        y0 = cy - total_h / 2.0
        for r in range(self._rows):
            y = y0 + r * self._sy
            for c in range(self._cols):
                x = cx + (c - 0.5) * self._sx
                p.drawEllipse(QPointF(x, y), self._dot_r, self._dot_r)
        p.end()


class ThemedSplitter(QSplitter):
    """自动应用主题 QSS 的 QSplitter

    创建时自动通过 ``StyleSheet.THEMED_SPLITTER`` 加载对应
    dark / light 主题的样式表，切换主题时自动刷新。
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None, handle_width=7):
        super().__init__(orientation, parent)
        self._handle_width = handle_width
        StyleSheet.THEMED_SPLITTER.apply(self)

    def createHandle(self):
        return ThemedSplitterHandle(self.orientation(), self, self._handle_width)
