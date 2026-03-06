"""流程图可视化编辑器 - 节点式编辑器

功能: 箭头连接线 / 网格吸附 / 框选 / 撤销重做 / 复制粘贴 /
      调试高亮 / 小地图 / 导出图片 / 自动布局 / 右键菜单
"""

import json
import math
from collections import defaultdict, deque
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont,
    QTransform, QWheelEvent, QMouseEvent, QImage, QPolygonF,
)
from PyQt5.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsObject,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsItem,
    QGraphicsDropShadowEffect, QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem, QWidget, QMenu,
)
from qfluentwidgets import isDarkTheme

from src.vstain.models.flow_model import (
    FlowNode, FlowConnection, FlowChart, NodeType,
    NODE_TYPE_LABELS, NODE_TYPE_COLORS, PortDef,
)

# ---------- 常量 ----------
NODE_WIDTH = 180
NODE_HEADER_H = 30
NODE_PORT_SPACING = 28
NODE_PORT_RADIUS = 6
NODE_BORDER_RADIUS = 8
NODE_BOTTOM_PAD = 8
GRID_SIZE = 20
GRID_SIZE_MAJOR = 100
ARROW_SIZE = 8
SNAP_SIZE = GRID_SIZE

SELECTION_COLOR = QColor(33, 150, 243)
PORT_HOVER_COLOR = QColor(33, 150, 243)
DEBUG_COLOR = QColor(76, 175, 80)


def _tc():
    d = isDarkTheme()
    return {
        "grid": QColor(50, 50, 55) if d else QColor(225, 225, 225),
        "grid_major": QColor(60, 60, 65) if d else QColor(200, 200, 200),
        "bg": QColor(30, 30, 30) if d else QColor(245, 245, 245),
        "node_bg": QColor(45, 45, 48) if d else QColor(255, 255, 255),
        "node_border": QColor(70, 70, 70) if d else QColor(200, 200, 200),
        "text": QColor(220, 220, 220) if d else QColor(50, 50, 50),
        "text_dim": QColor(150, 150, 150) if d else QColor(120, 120, 120),
        "port": QColor(170, 170, 170) if d else QColor(140, 140, 140),
        "conn": QColor(170, 170, 170) if d else QColor(130, 130, 130),
    }


# ================================================================
#  撤销管理器
# ================================================================
class _UndoManager:
    def __init__(self, limit=50):
        self._history: List[str] = []
        self._pos = -1
        self._limit = limit

    def push(self, state: str):
        self._history = self._history[: self._pos + 1]
        self._history.append(state)
        if len(self._history) > self._limit:
            self._history.pop(0)
        self._pos = len(self._history) - 1

    def can_undo(self):
        return self._pos > 0

    def can_redo(self):
        return self._pos < len(self._history) - 1

    def undo(self) -> Optional[str]:
        if self.can_undo():
            self._pos -= 1
            return self._history[self._pos]
        return None

    def redo(self) -> Optional[str]:
        if self.can_redo():
            self._pos += 1
            return self._history[self._pos]
        return None


# ================================================================
#  端口
# ================================================================
class FlowPortItem(QGraphicsEllipseItem):
    def __init__(self, port_def: PortDef, node_item: "FlowNodeItem"):
        r = NODE_PORT_RADIUS
        super().__init__(-r, -r, r * 2, r * 2)
        self.port_def = port_def
        self.node_item = node_item
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(_tc()["port"]))
        self.setCursor(Qt.CrossCursor)
        self.setZValue(2)

    @property
    def is_input(self):
        return self.port_def.is_input

    @property
    def port_id(self):
        return self.port_def.id

    @property
    def node_id(self):
        return self.node_item.flow_node.id

    def center_scene_pos(self):
        return self.scenePos()

    def hoverEnterEvent(self, e):
        self.setBrush(QBrush(PORT_HOVER_COLOR))
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        self.setBrush(QBrush(_tc()["port"]))
        super().hoverLeaveEvent(e)


# ================================================================
#  节点
# ================================================================
class FlowNodeItem(QGraphicsObject):
    position_changed = pyqtSignal()
    selected_changed = pyqtSignal(bool)
    drag_finished = pyqtSignal()

    def __init__(self, flow_node: FlowNode, parent=None):
        super().__init__(parent)
        self.flow_node = flow_node
        self.port_items: Dict[str, FlowPortItem] = {}
        self._debug_active = False

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

    def set_debug_active(self, active: bool):
        self._debug_active = active
        self.update()

    def _create_ports(self):
        ports = self.flow_node.get_ports()
        inputs = [p for p in ports if p.is_input]
        outputs = [p for p in ports if not p.is_input]
        for i, p in enumerate(inputs):
            it = FlowPortItem(p, self)
            it.setParentItem(self)
            it.setPos(0, NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5))
            self.port_items[p.id] = it
        for i, p in enumerate(outputs):
            it = FlowPortItem(p, self)
            it.setParentItem(self)
            it.setPos(NODE_WIDTH, NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5))
            self.port_items[p.id] = it

    @property
    def node_height(self) -> float:
        ports = self.flow_node.get_ports()
        ni = sum(1 for p in ports if p.is_input)
        no = sum(1 for p in ports if not p.is_input)
        rows = max(ni, no, 1)
        h = NODE_HEADER_H + NODE_PORT_SPACING * rows
        if self._summary_text():
            h += 22
        return h + NODE_BOTTOM_PAD

    def boundingRect(self):
        m = 4
        return QRectF(-m, -m, NODE_WIDTH + 2 * m, self.node_height + 2 * m)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        tc = _tc()
        h = self.node_height
        rect = QRectF(0, 0, NODE_WIDTH, h)

        if self._debug_active:
            bc, bw = DEBUG_COLOR, 3.0
        elif self.isSelected():
            bc, bw = SELECTION_COLOR, 2.0
        else:
            bc, bw = tc["node_border"], 1.0

        body = QPainterPath()
        body.addRoundedRect(rect, NODE_BORDER_RADIUS, NODE_BORDER_RADIUS)
        painter.setPen(QPen(bc, bw))
        painter.setBrush(QBrush(tc["node_bg"]))
        painter.drawPath(body)

        hdr_color = QColor(NODE_TYPE_COLORS[self.flow_node.node_type])
        r = NODE_BORDER_RADIUS
        hdr = QPainterPath()
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

        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(QRectF(0, 0, NODE_WIDTH, NODE_HEADER_H), Qt.AlignCenter,
                         NODE_TYPE_LABELS[self.flow_node.node_type])

        painter.setFont(QFont("Microsoft YaHei", 8))
        ports = self.flow_node.get_ports()
        ins = [p for p in ports if p.is_input]
        outs = [p for p in ports if not p.is_input]
        painter.setPen(QPen(tc["text"]))
        for i, p in enumerate(ins):
            y = NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5)
            painter.drawText(QRectF(NODE_PORT_RADIUS + 5, y - 10, NODE_WIDTH / 2 - NODE_PORT_RADIUS, 20),
                             Qt.AlignLeft | Qt.AlignVCenter, p.label)
        for i, p in enumerate(outs):
            y = NODE_HEADER_H + NODE_PORT_SPACING * (i + 0.5)
            painter.drawText(QRectF(NODE_WIDTH / 2, y - 10, NODE_WIDTH / 2 - NODE_PORT_RADIUS - 5, 20),
                             Qt.AlignRight | Qt.AlignVCenter, p.label)

        summary = self._summary_text()
        if summary:
            painter.setPen(QPen(tc["text_dim"]))
            painter.setFont(QFont("Microsoft YaHei", 7))
            ni2 = sum(1 for p in ports if p.is_input)
            no2 = sum(1 for p in ports if not p.is_input)
            rows = max(ni2, no2, 1)
            sy = NODE_HEADER_H + NODE_PORT_SPACING * rows + 2
            painter.drawText(QRectF(8, sy, NODE_WIDTH - 16, 18), Qt.AlignLeft | Qt.AlignVCenter, summary)

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
            lb = f"×{mx}" if mx >= 0 else "∞"
            return f"{lb}  {cv}" if cv else lb
        if nt == NodeType.SET_VARIABLE:
            v, val = p.get("variable", ""), p.get("value", "")
            return f"{v} = {val}" if v else ""
        if nt == NodeType.SCRIPT_REPLAY:
            return p.get("script_name", "") or ""
        if nt == NodeType.KEY_INPUT:
            return f"{p.get('key', '')} ({p.get('action', 'tap')})"
        if nt == NodeType.SWIPE:
            return f"({p.get('x1',0)},{p.get('y1',0)})→({p.get('x2',0)},{p.get('y2',0)})"
        if nt == NodeType.WAIT:
            return f"{p.get('seconds', 1.0)}s"
        if nt == NodeType.OCR_SCAN:
            return f"conf: {p.get('confidence', 0.5)}"
        if nt == NodeType.LOG:
            return p.get("message", "") or ""
        if nt == NodeType.COMMENT:
            return p.get("text", "") or ""
        if nt == NodeType.SUBFLOW:
            return p.get("flow_file", "") or ""
        return ""

    # ---------- 事件 ----------
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(
                round(value.x() / SNAP_SIZE) * SNAP_SIZE,
                round(value.y() / SNAP_SIZE) * SNAP_SIZE,
            )
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.flow_node.x = self.pos().x()
            self.flow_node.y = self.pos().y()
            self.position_changed.emit()
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self.selected_changed.emit(bool(value))
        return super().itemChange(change, value)

    def get_port_item(self, port_id: str) -> Optional[FlowPortItem]:
        return self.port_items.get(port_id)

    def mousePressEvent(self, e):
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.OpenHandCursor)
        self.drag_finished.emit()
        super().mouseReleaseEvent(e)


# ================================================================
#  连接线 (带箭头)
# ================================================================
def _bezier(start: QPointF, end: QPointF) -> QPainterPath:
    dx = max(abs(end.x() - start.x()) * 0.5, 50)
    p = QPainterPath()
    p.moveTo(start)
    p.cubicTo(start.x() + dx, start.y(), end.x() - dx, end.y(), end.x(), end.y())
    return p


ORDER_BADGE_RADIUS = 9
ORDER_BADGE_COLOR = QColor(33, 150, 243)


class FlowConnectionItem(QGraphicsPathItem):
    def __init__(self, connection: FlowConnection, sp: FlowPortItem, tp: FlowPortItem):
        super().__init__()
        self.connection = connection
        self.source_port = sp
        self.target_port = tp
        self._show_order = False
        self._order_rank = 1
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        self.setPath(_bezier(self.source_port.center_scene_pos(), self.target_port.center_scene_pos()))

    def boundingRect(self):
        r = super().boundingRect()
        if self._show_order:
            r.adjust(-ORDER_BADGE_RADIUS, -ORDER_BADGE_RADIUS,
                     ORDER_BADGE_RADIUS, ORDER_BADGE_RADIUS)
        return r

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        tc = _tc()
        color = SELECTION_COLOR if self.isSelected() else tc["conn"]
        w = 2.5 if self.isSelected() else 2.0
        painter.setPen(QPen(color, w))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

        path = self.path()
        if path.length() < 1:
            return
        t = min(0.97, 1.0)
        p1 = path.pointAtPercent(t)
        p2 = path.pointAtPercent(1.0)
        angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        a1 = QPointF(p2.x() - ARROW_SIZE * math.cos(angle - math.pi / 6),
                      p2.y() - ARROW_SIZE * math.sin(angle - math.pi / 6))
        a2 = QPointF(p2.x() - ARROW_SIZE * math.cos(angle + math.pi / 6),
                      p2.y() - ARROW_SIZE * math.sin(angle + math.pi / 6))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([p2, a1, a2]))

        if self._show_order and path.length() > 1:
            bp = path.pointAtPercent(0.18)
            r = ORDER_BADGE_RADIUS
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QBrush(ORDER_BADGE_COLOR))
            painter.drawEllipse(bp, r, r)
            painter.setFont(QFont("Microsoft YaHei", 7, QFont.Bold))
            painter.drawText(
                QRectF(bp.x() - r, bp.y() - r, r * 2, r * 2),
                Qt.AlignCenter, str(self._order_rank),
            )

    def shape(self) -> QPainterPath:
        from PyQt5.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(12)
        return s.createStroke(self.path())


class _TempConnectionItem(QGraphicsPathItem):
    def __init__(self, start_pos: QPointF):
        super().__init__()
        self.start_pos = start_pos
        self.setPen(QPen(QColor(120, 120, 120), 2, Qt.DashLine))
        self.setZValue(-1)

    def update_end(self, end_pos: QPointF):
        self.setPath(_bezier(self.start_pos, end_pos))


# ================================================================
#  场景
# ================================================================
class FlowScene(QGraphicsScene):
    node_selected = pyqtSignal(object)
    flow_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow_chart = FlowChart()
        self.node_items: Dict[str, FlowNodeItem] = {}
        self.connection_items: Dict[str, FlowConnectionItem] = {}
        self._temp_conn: Optional[_TempConnectionItem] = None
        self._drag_port: Optional[FlowPortItem] = None
        self._undo = _UndoManager()
        self._clipboard: Optional[str] = None
        self.setSceneRect(-3000, -3000, 6000, 6000)
        self._push_undo()
        self.flow_changed.connect(self._update_order_badges)

    # ---------- 撤销 ----------
    def _snapshot(self) -> str:
        return json.dumps({
            "nodes": [n.to_dict() for n in self.flow_chart.nodes],
            "connections": [c.to_dict() for c in self.flow_chart.connections],
            "variables": self.flow_chart.variables,
        }, ensure_ascii=False)

    def _push_undo(self):
        self._undo.push(self._snapshot())

    def _restore(self, state: str):
        data = json.loads(state)
        chart = FlowChart()
        chart.nodes = [FlowNode.from_dict(n) for n in data.get("nodes", [])]
        chart.connections = [FlowConnection.from_dict(c) for c in data.get("connections", [])]
        chart.variables = data.get("variables", {})
        self.load_flow_chart(chart, push_undo=False)

    def undo(self):
        s = self._undo.undo()
        if s:
            self._restore(s)

    def redo(self):
        s = self._undo.redo()
        if s:
            self._restore(s)

    # ---------- 复制粘贴 ----------
    def copy_selected(self):
        sel = [it for it in self.selectedItems() if isinstance(it, FlowNodeItem)]
        if not sel:
            return
        ids = {it.flow_node.id for it in sel}
        nodes = [it.flow_node.to_dict() for it in sel]
        conns = [c.to_dict() for c in self.flow_chart.connections
                 if c.source_node_id in ids and c.target_node_id in ids]
        self._clipboard = json.dumps({"nodes": nodes, "connections": conns}, ensure_ascii=False)

    def paste(self, offset_x=40, offset_y=40):
        if not self._clipboard:
            return
        data = json.loads(self._clipboard)
        import uuid
        id_map = {}
        for nd in data["nodes"]:
            old_id = nd["id"]
            new_id = uuid.uuid4().hex[:8]
            id_map[old_id] = new_id
            nd["id"] = new_id
            nd["x"] += offset_x
            nd["y"] += offset_y
        for cd in data["connections"]:
            cd["id"] = uuid.uuid4().hex[:8]
            cd["source_node"] = id_map.get(cd["source_node"], cd["source_node"])
            cd["target_node"] = id_map.get(cd["target_node"], cd["target_node"])

        for nd in data["nodes"]:
            node = FlowNode.from_dict(nd)
            self.flow_chart.add_node(node)
            item = self._make_node_item(node)
            item.setSelected(True)
        for cd in data["connections"]:
            conn = FlowConnection.from_dict(cd)
            self.flow_chart.add_connection(conn)
            self._make_conn_item(conn)
        self._push_undo()
        self.flow_changed.emit()

    # ---------- 背景网格 ----------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        tc = _tc()
        painter.fillRect(rect, QBrush(tc["bg"]))
        left = int(rect.left()) - int(rect.left()) % GRID_SIZE
        top = int(rect.top()) - int(rect.top()) % GRID_SIZE
        painter.setPen(QPen(tc["grid"], 0.5))
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID_SIZE
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID_SIZE
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

    # ---------- 节点 CRUD ----------
    def _make_node_item(self, node: FlowNode) -> FlowNodeItem:
        item = FlowNodeItem(node)
        item.position_changed.connect(self._on_node_moved)
        item.selected_changed.connect(lambda sel, n=node: self._on_node_selected(n, sel))
        item.drag_finished.connect(self._push_undo)
        self.addItem(item)
        self.node_items[node.id] = item
        return item

    def _make_conn_item(self, conn: FlowConnection) -> Optional[FlowConnectionItem]:
        sni = self.node_items.get(conn.source_node_id)
        tni = self.node_items.get(conn.target_node_id)
        if sni and tni:
            sp = sni.get_port_item(conn.source_port_id)
            tp = tni.get_port_item(conn.target_port_id)
            if sp and tp:
                ci = FlowConnectionItem(conn, sp, tp)
                self.addItem(ci)
                self.connection_items[conn.id] = ci
                return ci
        return None

    def add_node(self, node_type: NodeType, x=0.0, y=0.0) -> FlowNodeItem:
        node = FlowNode.create(node_type, x, y)
        self.flow_chart.add_node(node)
        item = self._make_node_item(node)
        self._push_undo()
        self.flow_changed.emit()
        return item

    def remove_node_by_id(self, node_id: str):
        item = self.node_items.get(node_id)
        if not item:
            return
        for cid in [c.id for c in self.flow_chart.connections
                     if c.source_node_id == node_id or c.target_node_id == node_id]:
            if cid in self.connection_items:
                self.removeItem(self.connection_items.pop(cid))
        self.flow_chart.remove_node(node_id)
        self.removeItem(item)
        self.node_items.pop(node_id, None)
        self.node_selected.emit(None)
        self._push_undo()
        self.flow_changed.emit()

    def remove_connection_by_id(self, conn_id: str):
        item = self.connection_items.get(conn_id)
        if not item:
            return
        self.flow_chart.remove_connection(conn_id)
        self.removeItem(item)
        self.connection_items.pop(conn_id, None)
        self._push_undo()
        self.flow_changed.emit()

    def remove_selected(self):
        removed = False
        for item in list(self.selectedItems()):
            if isinstance(item, FlowNodeItem):
                nid = item.flow_node.id
                for cid in [c.id for c in self.flow_chart.connections
                             if c.source_node_id == nid or c.target_node_id == nid]:
                    if cid in self.connection_items:
                        self.removeItem(self.connection_items.pop(cid))
                self.flow_chart.remove_node(nid)
                self.removeItem(item)
                self.node_items.pop(nid, None)
                removed = True
            elif isinstance(item, FlowConnectionItem):
                self.flow_chart.remove_connection(item.connection.id)
                self.removeItem(item)
                self.connection_items.pop(item.connection.id, None)
                removed = True
        if removed:
            self.node_selected.emit(None)
            self._push_undo()
            self.flow_changed.emit()

    # ---------- 连接顺序 ----------
    def _update_order_badges(self):
        groups: Dict[tuple, list] = defaultdict(list)
        for c in self.flow_chart.connections:
            groups[(c.source_node_id, c.source_port_id)].append(c)
        ranks: Dict[str, int] = {}
        for conns in groups.values():
            conns.sort(key=lambda c: c.order)
            for i, c in enumerate(conns):
                ranks[c.id] = i + 1
        for ci in self.connection_items.values():
            c = ci.connection
            show = len(groups[(c.source_node_id, c.source_port_id)]) > 1
            rank = ranks.get(c.id, 1)
            if ci._show_order != show or ci._order_rank != rank:
                ci._show_order = show
                ci._order_rank = rank
                ci.update()

    def reorder_connection(self, conn_id: str, delta: int):
        self.flow_chart.swap_connection_order(conn_id, delta)
        self._push_undo()
        self.flow_changed.emit()

    # ---------- 连接 ----------
    def _create_connection(self, sp: FlowPortItem, tp: FlowPortItem):
        if sp.is_input or not tp.is_input:
            return
        if sp.node_id == tp.node_id:
            return
        for ci in self.connection_items.values():
            c = ci.connection
            if (c.source_node_id == sp.node_id and c.source_port_id == sp.port_id
                    and c.target_node_id == tp.node_id and c.target_port_id == tp.port_id):
                return
        conn = FlowConnection.create(sp.node_id, sp.port_id, tp.node_id, tp.port_id)
        self.flow_chart.add_connection(conn)
        item = FlowConnectionItem(conn, sp, tp)
        self.addItem(item)
        self.connection_items[conn.id] = item
        self._push_undo()
        self.flow_changed.emit()

    def _on_node_moved(self):
        for ci in self.connection_items.values():
            ci.update_path()

    def _on_node_selected(self, node, sel):
        if sel:
            self.node_selected.emit(node)
        elif not any(it.isSelected() for it in self.node_items.values()):
            self.node_selected.emit(None)

    # ---------- 调试高亮 ----------
    def highlight_node(self, node_id: str):
        for nid, item in self.node_items.items():
            item.set_debug_active(nid == node_id)

    def clear_highlight(self):
        for item in self.node_items.values():
            item.set_debug_active(False)

    # ---------- 自动布局 ----------
    def auto_layout(self):
        chart = self.flow_chart
        if not chart.nodes:
            return
        adj: Dict[str, List[str]] = {n.id: [] for n in chart.nodes}
        in_deg: Dict[str, int] = {n.id: 0 for n in chart.nodes}
        for c in chart.connections:
            if c.target_node_id in adj:
                adj[c.source_node_id].append(c.target_node_id)
                in_deg[c.target_node_id] = in_deg.get(c.target_node_id, 0) + 1

        layers: Dict[str, int] = {}
        q = deque([nid for nid, d in in_deg.items() if d == 0])
        for nid in q:
            layers.setdefault(nid, 0)
        while q:
            nid = q.popleft()
            for child in adj.get(nid, []):
                layers[child] = max(layers.get(child, 0), layers[nid] + 1)
                in_deg[child] -= 1
                if in_deg[child] <= 0 and child not in [x for x in q]:
                    q.append(child)
        ml = max(layers.values(), default=0) + 1
        for n in chart.nodes:
            if n.id not in layers:
                layers[n.id] = ml
                ml += 1
        groups: Dict[int, List[str]] = {}
        for nid, l in layers.items():
            groups.setdefault(l, []).append(nid)
        for l, nids in groups.items():
            for i, nid in enumerate(nids):
                node = chart.get_node(nid)
                if node:
                    node.x = l * 260
                    node.y = i * 120
        for nid, item in self.node_items.items():
            node = chart.get_node(nid)
            if node:
                item.setPos(node.x, node.y)
        for ci in self.connection_items.values():
            ci.update_path()
        self._push_undo()
        self.flow_changed.emit()

    # ---------- 导出图片 ----------
    def export_image(self, filepath: str):
        rect = self.itemsBoundingRect()
        rect.adjust(-30, -30, 30, 30)
        img = QImage(max(int(rect.width()), 1), max(int(rect.height()), 1), QImage.Format_ARGB32)
        img.fill(QColor(30, 30, 30))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self.render(painter, QRectF(img.rect()), rect)
        painter.end()
        img.save(filepath)

    # ---------- 鼠标事件 ----------
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
    def load_flow_chart(self, chart: FlowChart, push_undo=True):
        self.clear()
        self.node_items.clear()
        self.connection_items.clear()
        self.flow_chart = chart
        for node in chart.nodes:
            self._make_node_item(node)
        for conn in chart.connections:
            self._make_conn_item(conn)
        if push_undo:
            self._push_undo()
        self.flow_changed.emit()


# ================================================================
#  画布
# ================================================================
class FlowCanvas(QGraphicsView):
    def __init__(self, scene: FlowScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QGraphicsView { border: none; }")

        self._panning = False
        self._pan_start = QPointF()
        self._zoom = 1.0
        self._right_press_pos = None
        self._right_dragging = False

    def wheelEvent(self, event: QWheelEvent):
        f = 1.15
        if event.angleDelta().y() > 0:
            if self._zoom < 3.0:
                self.scale(f, f); self._zoom *= f
        else:
            if self._zoom > 0.2:
                self.scale(1/f, 1/f); self._zoom /= f

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
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            hit = self.scene().itemAt(scene_pos, QTransform())
            if isinstance(hit, FlowPortItem):
                self.setDragMode(QGraphicsView.NoDrag)
            else:
                self.setDragMode(QGraphicsView.RubberBandDrag)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            d = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
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
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.dragMode() == QGraphicsView.NoDrag:
            self.setDragMode(QGraphicsView.RubberBandDrag)
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False; self.setCursor(Qt.ArrowCursor); return
        if event.button() == Qt.RightButton:
            was = self._right_dragging
            self._right_press_pos = None
            self._right_dragging = False
            if self._panning:
                self._panning = False; self.setCursor(Qt.ArrowCursor)
            if not was:
                self._show_ctx(event.pos(), event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        mod = event.modifiers()
        key = event.key()
        sc: FlowScene = self.scene()
        if key == Qt.Key_Delete:
            sc.remove_selected(); return
        if mod & Qt.ControlModifier:
            if key == Qt.Key_Z:
                sc.undo(); return
            if key == Qt.Key_Y:
                sc.redo(); return
            if key == Qt.Key_C:
                sc.copy_selected(); return
            if key == Qt.Key_V:
                sc.paste(); return
            if key == Qt.Key_A:
                for it in sc.items():
                    if isinstance(it, (FlowNodeItem, FlowConnectionItem)):
                        it.setSelected(True)
                return
        super().keyPressEvent(event)

    def _show_ctx(self, vp, gp):
        sp = self.mapToScene(vp)
        item = self.scene().itemAt(sp, self.transform())
        if isinstance(item, FlowPortItem):
            item = item.node_item
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:palette(window);border:1px solid palette(mid);border-radius:6px;padding:4px;}"
            "QMenu::item{padding:6px 24px;border-radius:4px;}"
            "QMenu::item:selected{background:palette(highlight);color:palette(highlighted-text);}"
            "QMenu::separator{height:1px;background:palette(mid);margin:4px 8px;}"
        )
        sc: FlowScene = self.scene()
        if isinstance(item, FlowNodeItem):
            menu.addAction("删除节点").triggered.connect(lambda: sc.remove_node_by_id(item.flow_node.id))
        elif isinstance(item, FlowConnectionItem):
            conn = item.connection
            siblings = sc.flow_chart.get_connections_from(
                conn.source_node_id, conn.source_port_id)
            if len(siblings) > 1:
                idx = next((i for i, c in enumerate(siblings) if c.id == conn.id), 0)
                if idx > 0:
                    menu.addAction("上移优先级 ↑").triggered.connect(
                        lambda: sc.reorder_connection(conn.id, -1))
                if idx < len(siblings) - 1:
                    menu.addAction("下移优先级 ↓").triggered.connect(
                        lambda: sc.reorder_connection(conn.id, 1))
                menu.addSeparator()
            menu.addAction("删除连接").triggered.connect(lambda: sc.remove_connection_by_id(conn.id))
        else:
            sub = menu.addMenu("添加节点")
            for nt in NodeType:
                sub.addAction(NODE_TYPE_LABELS[nt]).triggered.connect(
                    lambda chk, _n=nt, _p=sp: sc.add_node(_n, _p.x(), _p.y()))
            menu.addSeparator()
            menu.addAction("全选  Ctrl+A").triggered.connect(
                lambda: [it.setSelected(True) for it in sc.items() if isinstance(it, (FlowNodeItem, FlowConnectionItem))])
            menu.addAction("撤销  Ctrl+Z").triggered.connect(sc.undo)
            menu.addAction("重做  Ctrl+Y").triggered.connect(sc.redo)
        menu.exec_(gp)


# ================================================================
#  小地图
# ================================================================
class FlowMinimap(QGraphicsView):
    def __init__(self, main_scene: QGraphicsScene, main_view: QGraphicsView, parent=None):
        super().__init__(main_scene, parent or main_view)
        self._main = main_view
        self.setFixedSize(200, 150)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setInteractive(False)
        self.setStyleSheet("border:1px solid palette(mid);border-radius:4px;")

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QBrush(_tc()["bg"]))

    def drawForeground(self, painter, rect):
        if self._main:
            vr = self._main.mapToScene(self._main.viewport().rect()).boundingRect()
            painter.setPen(QPen(QColor(33, 150, 243, 150), 2))
            painter.setBrush(QBrush(QColor(33, 150, 243, 20)))
            painter.drawRect(vr)

    def refresh(self):
        r = self.scene().itemsBoundingRect()
        if r.isNull():
            return
        r.adjust(-80, -80, 80, 80)
        self.fitInView(r, Qt.KeepAspectRatio)
        self.viewport().update()

    def mousePressEvent(self, event):
        if self._main:
            self._main.centerOn(self.mapToScene(event.pos()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._main:
            self._main.centerOn(self.mapToScene(event.pos()))

    def reposition(self):
        pr = self.parent().rect() if self.parent() else QRectF()
        self.move(int(pr.width()) - self.width() - 8, int(pr.height()) - self.height() - 8)
