"""流程图可视化编辑器 - 基于 QGraphicsScene 的节点式编辑器"""

from typing import Dict, Optional

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QPainterPath,
    QFont,
    QTransform,
    QWheelEvent,
    QMouseEvent,
)
from PyQt5.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QGraphicsObject,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsItem,
    QGraphicsDropShadowEffect,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
    QMenu,
    QAction,
)
from qfluentwidgets import isDarkTheme

from src.vstain.models.flow_model import (
    FlowNode,
    FlowConnection,
    FlowChart,
    NodeType,
    NODE_TYPE_LABELS,
    NODE_TYPE_COLORS,
    PortDef,
)

# ---------- 尺寸常量 ----------
NODE_WIDTH = 180
NODE_HEADER_H = 30
NODE_PORT_SPACING = 28
NODE_PORT_RADIUS = 6
NODE_BORDER_RADIUS = 8
NODE_BOTTOM_PAD = 8
GRID_SIZE = 20
GRID_SIZE_MAJOR = 100


def _theme_colors():
    """根据当前主题返回一组配色"""
    dark = isDarkTheme()
    return {
        "grid": QColor(50, 50, 55) if dark else QColor(225, 225, 225),
        "grid_major": QColor(60, 60, 65) if dark else QColor(200, 200, 200),
        "bg": QColor(30, 30, 30) if dark else QColor(245, 245, 245),
        "node_bg": QColor(45, 45, 48) if dark else QColor(255, 255, 255),
        "node_border": QColor(70, 70, 70) if dark else QColor(200, 200, 200),
        "text": QColor(220, 220, 220) if dark else QColor(50, 50, 50),
        "text_dim": QColor(150, 150, 150) if dark else QColor(120, 120, 120),
        "port": QColor(170, 170, 170) if dark else QColor(140, 140, 140),
        "conn": QColor(170, 170, 170) if dark else QColor(130, 130, 130),
    }


SELECTION_COLOR = QColor(33, 150, 243)
PORT_HOVER_COLOR = QColor(33, 150, 243)


# ================================================================
#  端口 (Port)
# ================================================================
class FlowPortItem(QGraphicsEllipseItem):
    """节点上的端口圆圈，支持拖拽创建连接"""

    def __init__(self, port_def: PortDef, node_item: "FlowNodeItem"):
        r = NODE_PORT_RADIUS
        super().__init__(-r, -r, r * 2, r * 2)
        self.port_def = port_def
        self.node_item = node_item
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(_theme_colors()["port"]))
        self.setCursor(Qt.CrossCursor)
        self.setZValue(2)

    @property
    def is_input(self) -> bool:
        return self.port_def.is_input

    @property
    def port_id(self) -> str:
        return self.port_def.id

    @property
    def node_id(self) -> str:
        return self.node_item.flow_node.id

    def center_scene_pos(self) -> QPointF:
        return self.scenePos()

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(PORT_HOVER_COLOR))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(_theme_colors()["port"]))
        super().hoverLeaveEvent(event)


# ================================================================
#  节点 (Node)
# ================================================================
class FlowNodeItem(QGraphicsObject):
    """流程图节点图形项"""

    position_changed = pyqtSignal()
    selected_changed = pyqtSignal(bool)

    def __init__(self, flow_node: FlowNode, parent=None):
        super().__init__(parent)
        self.flow_node = flow_node
        self.port_items: Dict[str, FlowPortItem] = {}

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setPos(flow_node.x, flow_node.y)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(1)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(3, 3)
        self.setGraphicsEffect(shadow)

        self._create_ports()

    # ---------- 端口布局 ----------
    def _create_ports(self):
        ports = self.flow_node.get_ports()
        inputs = [p for p in ports if p.is_input]
        outputs = [p for p in ports if not p.is_input]

        for i, p in enumerate(inputs):
            item = FlowPortItem(p, self)
            item.setParentItem(self)
            item.setPos(0, NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5))
            self.port_items[p.id] = item

        for i, p in enumerate(outputs):
            item = FlowPortItem(p, self)
            item.setParentItem(self)
            item.setPos(NODE_WIDTH, NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5))
            self.port_items[p.id] = item

    # ---------- 几何 ----------
    @property
    def node_height(self) -> float:
        ports = self.flow_node.get_ports()
        n_in = sum(1 for p in ports if p.is_input)
        n_out = sum(1 for p in ports if not p.is_input)
        rows = max(n_in, n_out, 1)
        h = NODE_HEADER_H + NODE_PORT_SPACING * rows
        if self._summary_text():
            h += 22
        return h + NODE_BOTTOM_PAD

    def boundingRect(self) -> QRectF:
        m = 4
        return QRectF(-m, -m, NODE_WIDTH + 2 * m, self.node_height + 2 * m)

    # ---------- 绘制 ----------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        painter.setRenderHint(QPainter.Antialiasing)
        tc = _theme_colors()
        h = self.node_height
        rect = QRectF(0, 0, NODE_WIDTH, h)

        # 主体
        border_color = SELECTION_COLOR if self.isSelected() else tc["node_border"]
        border_w = 2.0 if self.isSelected() else 1.0
        body_path = QPainterPath()
        body_path.addRoundedRect(rect, NODE_BORDER_RADIUS, NODE_BORDER_RADIUS)
        painter.setPen(QPen(border_color, border_w))
        painter.setBrush(QBrush(tc["node_bg"]))
        painter.drawPath(body_path)

        # 表头
        hdr_color = QColor(NODE_TYPE_COLORS[self.flow_node.node_type])
        hdr = QPainterPath()
        r = NODE_BORDER_RADIUS
        hdr.moveTo(r, 0)
        hdr.lineTo(NODE_WIDTH - r, 0)
        hdr.arcTo(NODE_WIDTH - 2 * r, 0, 2 * r, 2 * r, 90, -90)
        hdr.lineTo(NODE_WIDTH, NODE_HEADER_H)
        hdr.lineTo(0, NODE_HEADER_H)
        hdr.lineTo(0, r)
        hdr.arcTo(0, 0, 2 * r, 2 * r, 180, -90)
        hdr.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(hdr_color))
        painter.drawPath(hdr)

        # 标题
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(QRectF(0, 0, NODE_WIDTH, NODE_HEADER_H), Qt.AlignCenter,
                         NODE_TYPE_LABELS[self.flow_node.node_type])

        # 端口标签
        painter.setFont(QFont("Microsoft YaHei", 8))
        ports = self.flow_node.get_ports()
        inputs = [p for p in ports if p.is_input]
        outputs = [p for p in ports if not p.is_input]

        painter.setPen(QPen(tc["text"]))
        for i, p in enumerate(inputs):
            y = NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5)
            r2 = QRectF(NODE_PORT_RADIUS + 5, y - 10, NODE_WIDTH / 2 - NODE_PORT_RADIUS, 20)
            painter.drawText(r2, Qt.AlignLeft | Qt.AlignVCenter, p.label)

        for i, p in enumerate(outputs):
            y = NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5)
            r2 = QRectF(NODE_WIDTH / 2, y - 10, NODE_WIDTH / 2 - NODE_PORT_RADIUS - 5, 20)
            painter.drawText(r2, Qt.AlignRight | Qt.AlignVCenter, p.label)

        # 属性摘要
        summary = self._summary_text()
        if summary:
            painter.setPen(QPen(tc["text_dim"]))
            painter.setFont(QFont("Microsoft YaHei", 7))
            n_in = sum(1 for p in ports if p.is_input)
            n_out = sum(1 for p in ports if not p.is_input)
            rows = max(n_in, n_out, 1)
            sy = NODE_HEADER_H + NODE_PORT_SPACING * rows + 2
            sr = QRectF(8, sy, NODE_WIDTH - 16, 18)
            painter.drawText(sr, Qt.AlignLeft | Qt.AlignVCenter, summary)

    def _summary_text(self) -> str:
        p = self.flow_node.properties
        nt = self.flow_node.node_type
        if nt == NodeType.TEXT_MATCH:
            return p.get("pattern", "") or ""
        if nt == NodeType.CONDITION:
            v, op, val = p.get("variable", ""), p.get("operator", "=="), p.get("value", "")
            return f"{v} {op} {val}" if v else ""
        if nt == NodeType.LOOP:
            mx = p.get("max_iterations", -1)
            cv = p.get("counter_variable", "")
            label = f"×{mx}" if mx >= 0 else "∞"
            return f"{label}  {cv}" if cv else label
        if nt == NodeType.SET_VARIABLE:
            v, val = p.get("variable", ""), p.get("value", "")
            return f"{v} = {val}" if v else ""
        if nt == NodeType.SCRIPT_REPLAY:
            return p.get("script_name", "") or ""
        if nt == NodeType.WAIT:
            return f"{p.get('seconds', 1.0)}s"
        if nt == NodeType.OCR_SCAN:
            return f"conf: {p.get('confidence', 0.5)}"
        if nt == NodeType.LOG:
            return p.get("message", "") or ""
        return ""

    # ---------- 事件 ----------
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.flow_node.x = self.pos().x()
            self.flow_node.y = self.pos().y()
            self.position_changed.emit()
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self.selected_changed.emit(bool(value))
        return super().itemChange(change, value)

    def get_port_item(self, port_id: str) -> Optional[FlowPortItem]:
        return self.port_items.get(port_id)

    def mousePressEvent(self, event):
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


# ================================================================
#  连接线 (Connection)
# ================================================================
def _bezier_path(start: QPointF, end: QPointF) -> QPainterPath:
    dx = max(abs(end.x() - start.x()) * 0.5, 50)
    path = QPainterPath()
    path.moveTo(start)
    path.cubicTo(start.x() + dx, start.y(), end.x() - dx, end.y(), end.x(), end.y())
    return path


class FlowConnectionItem(QGraphicsPathItem):
    """两个端口之间的贝塞尔曲线连接"""

    def __init__(self, connection: FlowConnection, src_port: FlowPortItem, tgt_port: FlowPortItem):
        super().__init__()
        self.connection = connection
        self.source_port = src_port
        self.target_port = tgt_port
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        start = self.source_port.center_scene_pos()
        end = self.target_port.center_scene_pos()
        self.setPath(_bezier_path(start, end))

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        tc = _theme_colors()
        color = SELECTION_COLOR if self.isSelected() else tc["conn"]
        width = 2.5 if self.isSelected() else 2.0
        painter.setPen(QPen(color, width))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

    def shape(self) -> QPainterPath:
        """加宽点击区域，使连接线更容易选中"""
        from PyQt5.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())


class _TempConnectionItem(QGraphicsPathItem):
    """拖拽创建连接时的临时虚线"""

    def __init__(self, start_pos: QPointF):
        super().__init__()
        self.start_pos = start_pos
        self.setPen(QPen(QColor(120, 120, 120), 2, Qt.DashLine))
        self.setZValue(-1)

    def update_end(self, end_pos: QPointF):
        self.setPath(_bezier_path(self.start_pos, end_pos))


# ================================================================
#  场景 (Scene)
# ================================================================
class FlowScene(QGraphicsScene):
    """管理所有节点和连接的场景"""

    node_selected = pyqtSignal(object)  # FlowNode | None
    flow_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow_chart = FlowChart()
        self.node_items: Dict[str, FlowNodeItem] = {}
        self.connection_items: Dict[str, FlowConnectionItem] = {}
        self._temp_conn: Optional[_TempConnectionItem] = None
        self._drag_port: Optional[FlowPortItem] = None
        self.setSceneRect(-3000, -3000, 6000, 6000)

    # ---------- 背景网格 ----------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        tc = _theme_colors()
        painter.fillRect(rect, QBrush(tc["bg"]))

        left = int(rect.left()) - int(rect.left()) % GRID_SIZE
        top = int(rect.top()) - int(rect.top()) % GRID_SIZE

        # 小网格
        painter.setPen(QPen(tc["grid"], 0.5))
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID_SIZE
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID_SIZE

        # 大网格
        left_m = int(rect.left()) - int(rect.left()) % GRID_SIZE_MAJOR
        top_m = int(rect.top()) - int(rect.top()) % GRID_SIZE_MAJOR
        painter.setPen(QPen(tc["grid_major"], 1))
        x = left_m
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID_SIZE_MAJOR
        y = top_m
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID_SIZE_MAJOR

    # ---------- 节点操作 ----------
    def add_node(self, node_type: NodeType, x: float = 0, y: float = 0) -> FlowNodeItem:
        node = FlowNode.create(node_type, x, y)
        self.flow_chart.add_node(node)
        item = FlowNodeItem(node)
        item.position_changed.connect(self._on_node_moved)
        item.selected_changed.connect(lambda sel, n=node: self._on_node_selected(n, sel))
        self.addItem(item)
        self.node_items[node.id] = item
        self.flow_changed.emit()
        return item

    def remove_node_by_id(self, node_id: str):
        item = self.node_items.get(node_id)
        if not item:
            return
        for cid in [
            c.id for c in self.flow_chart.connections
            if c.source_node_id == node_id or c.target_node_id == node_id
        ]:
            if cid in self.connection_items:
                self.removeItem(self.connection_items.pop(cid))
        self.flow_chart.remove_node(node_id)
        self.removeItem(item)
        self.node_items.pop(node_id, None)
        self.node_selected.emit(None)
        self.flow_changed.emit()

    def remove_connection_by_id(self, conn_id: str):
        item = self.connection_items.get(conn_id)
        if not item:
            return
        self.flow_chart.remove_connection(conn_id)
        self.removeItem(item)
        self.connection_items.pop(conn_id, None)
        self.flow_changed.emit()

    def remove_selected(self):
        removed = False
        for item in list(self.selectedItems()):
            if isinstance(item, FlowNodeItem):
                self.remove_node_by_id(item.flow_node.id)
                removed = True
            elif isinstance(item, FlowConnectionItem):
                self.remove_connection_by_id(item.connection.id)
                removed = True
        if removed:
            self.node_selected.emit(None)

    # ---------- 连接操作 ----------
    def _create_connection(self, src_port: FlowPortItem, tgt_port: FlowPortItem):
        if src_port.is_input or not tgt_port.is_input:
            return
        if src_port.node_id == tgt_port.node_id:
            return

        for ci in self.connection_items.values():
            c = ci.connection
            if (c.source_node_id == src_port.node_id
                    and c.source_port_id == src_port.port_id
                    and c.target_node_id == tgt_port.node_id
                    and c.target_port_id == tgt_port.port_id):
                return

        conn = FlowConnection.create(src_port.node_id, src_port.port_id, tgt_port.node_id, tgt_port.port_id)
        self.flow_chart.add_connection(conn)

        item = FlowConnectionItem(conn, src_port, tgt_port)
        self.addItem(item)
        self.connection_items[conn.id] = item
        self.flow_changed.emit()

    def _on_node_moved(self):
        for ci in self.connection_items.values():
            ci.update_path()

    def _on_node_selected(self, node: FlowNode, selected: bool):
        if selected:
            self.node_selected.emit(node)
        elif not any(it.isSelected() for it in self.node_items.values()):
            self.node_selected.emit(None)

    # ---------- 鼠标事件(端口拖拽) ----------
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, FlowPortItem) and event.button() == Qt.LeftButton:
            self._drag_port = item
            self._temp_conn = _TempConnectionItem(item.center_scene_pos())
            self.addItem(self._temp_conn)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._temp_conn is not None:
            self._temp_conn.update_end(event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._temp_conn is not None:
            self.removeItem(self._temp_conn)
            self._temp_conn = None
            target = self.itemAt(event.scenePos(), QTransform())
            if isinstance(target, FlowPortItem) and target is not self._drag_port:
                if self._drag_port.is_input and not target.is_input:
                    self._create_connection(target, self._drag_port)
                elif not self._drag_port.is_input and target.is_input:
                    self._create_connection(self._drag_port, target)
            self._drag_port = None
            return
        super().mouseReleaseEvent(event)

    # ---------- 加载 ----------
    def load_flow_chart(self, chart: FlowChart):
        self.clear()
        self.node_items.clear()
        self.connection_items.clear()
        self.flow_chart = chart

        for node in chart.nodes:
            item = FlowNodeItem(node)
            item.position_changed.connect(self._on_node_moved)
            item.selected_changed.connect(lambda sel, n=node: self._on_node_selected(n, sel))
            self.addItem(item)
            self.node_items[node.id] = item

        for conn in chart.connections:
            src_ni = self.node_items.get(conn.source_node_id)
            tgt_ni = self.node_items.get(conn.target_node_id)
            if src_ni and tgt_ni:
                sp = src_ni.get_port_item(conn.source_port_id)
                tp = tgt_ni.get_port_item(conn.target_port_id)
                if sp and tp:
                    ci = FlowConnectionItem(conn, sp, tp)
                    self.addItem(ci)
                    self.connection_items[conn.id] = ci

        self.flow_changed.emit()


# ================================================================
#  画布 (Canvas / View)
# ================================================================
class FlowCanvas(QGraphicsView):
    """支持平移、缩放和右键菜单的流程图画布"""

    def __init__(self, scene: FlowScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QGraphicsView { border: none; }")
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self._panning = False
        self._pan_start = QPointF()
        self._zoom = 1.0
        self._right_press_pos = None
        self._right_dragging = False

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        if event.angleDelta().y() > 0:
            if self._zoom < 3.0:
                self.scale(factor, factor)
                self._zoom *= factor
        else:
            if self._zoom > 0.2:
                self.scale(1 / factor, 1 / factor)
                self._zoom /= factor

    # ---------- 平移 (中键 + 右键拖拽) ----------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.RightButton:
            self._right_press_pos = event.pos()
            self._right_dragging = False
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(hs.value() - int(delta.x()))
            vs.setValue(vs.value() - int(delta.y()))
            return
        if self._right_press_pos is not None and (event.buttons() & Qt.RightButton):
            delta = event.pos() - self._right_press_pos
            if not self._right_dragging and delta.manhattanLength() > 8:
                self._right_dragging = True
                self._panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
            if self._panning:
                d = event.pos() - self._pan_start
                self._pan_start = event.pos()
                hs = self.horizontalScrollBar()
                vs = self.verticalScrollBar()
                hs.setValue(hs.value() - int(d.x()))
                vs.setValue(vs.value() - int(d.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        if event.button() == Qt.RightButton:
            was_dragging = self._right_dragging
            self._right_press_pos = None
            self._right_dragging = False
            if self._panning:
                self._panning = False
                self.setCursor(Qt.ArrowCursor)
            if not was_dragging:
                self._show_context_menu(event.pos(), event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.scene().remove_selected()
            return
        super().keyPressEvent(event)

    # ---------- 右键菜单 ----------
    def _show_context_menu(self, view_pos, global_pos):
        scene_pos = self.mapToScene(view_pos)
        item = self.scene().itemAt(scene_pos, self.transform())

        if isinstance(item, FlowPortItem):
            item = item.node_item

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: palette(window); border: 1px solid palette(mid); border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 24px; border-radius: 4px; }
            QMenu::item:selected { background: palette(highlight); color: palette(highlighted-text); }
            QMenu::separator { height: 1px; background: palette(mid); margin: 4px 8px; }
        """)

        if isinstance(item, FlowNodeItem):
            act_del = menu.addAction("删除节点")
            act_del.triggered.connect(lambda: self.scene().remove_node_by_id(item.flow_node.id))
        elif isinstance(item, FlowConnectionItem):
            act_del = menu.addAction("删除连接")
            act_del.triggered.connect(lambda: self.scene().remove_connection_by_id(item.connection.id))
        else:
            add_menu = menu.addMenu("添加节点")
            for nt in NodeType:
                act = add_menu.addAction(NODE_TYPE_LABELS[nt])
                act.triggered.connect(
                    lambda checked, _nt=nt, _p=scene_pos: self.scene().add_node(_nt, _p.x(), _p.y())
                )
            menu.addSeparator()
            act_sel_all = menu.addAction("全选")
            act_sel_all.triggered.connect(self._select_all)

        menu.exec_(global_pos)

    def _select_all(self):
        for item in self.scene().items():
            if isinstance(item, (FlowNodeItem, FlowConnectionItem)):
                item.setSelected(True)
