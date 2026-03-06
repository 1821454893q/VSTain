"""流程图数据模型 - 节点、连接、流程图的定义与序列化"""

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(Enum):
    START = "start"
    OCR_SCAN = "ocr_scan"
    TEXT_MATCH = "text_match"
    CONDITION = "condition"
    CLICK = "click"
    SET_VARIABLE = "set_variable"
    SCRIPT_REPLAY = "script_replay"
    WAIT = "wait"


NODE_TYPE_LABELS = {
    NodeType.START: "开始",
    NodeType.OCR_SCAN: "OCR 扫描",
    NodeType.TEXT_MATCH: "文本匹配",
    NodeType.CONDITION: "条件判断",
    NodeType.CLICK: "点击",
    NodeType.SET_VARIABLE: "设置变量",
    NodeType.SCRIPT_REPLAY: "脚本回放",
    NodeType.WAIT: "等待",
}

NODE_TYPE_COLORS = {
    NodeType.START: "#4CAF50",
    NodeType.OCR_SCAN: "#2196F3",
    NodeType.TEXT_MATCH: "#FF9800",
    NodeType.CONDITION: "#9C27B0",
    NodeType.CLICK: "#F44336",
    NodeType.SET_VARIABLE: "#009688",
    NodeType.SCRIPT_REPLAY: "#3F51B5",
    NodeType.WAIT: "#607D8B",
}


@dataclass
class PortDef:
    id: str
    label: str
    is_input: bool


NODE_TYPE_PORTS: Dict[NodeType, List[PortDef]] = {
    NodeType.START: [
        PortDef("out", "输出", False),
    ],
    NodeType.OCR_SCAN: [
        PortDef("in", "输入", True),
        PortDef("out", "输出", False),
    ],
    NodeType.TEXT_MATCH: [
        PortDef("in", "输入", True),
        PortDef("matched", "匹配 ✓", False),
        PortDef("not_matched", "不匹配 ✗", False),
    ],
    NodeType.CONDITION: [
        PortDef("in", "输入", True),
        PortDef("true", "True", False),
        PortDef("false", "False", False),
    ],
    NodeType.CLICK: [
        PortDef("in", "输入", True),
        PortDef("out", "输出", False),
    ],
    NodeType.SET_VARIABLE: [
        PortDef("in", "输入", True),
        PortDef("out", "输出", False),
    ],
    NodeType.SCRIPT_REPLAY: [
        PortDef("in", "输入", True),
        PortDef("out", "输出", False),
    ],
    NodeType.WAIT: [
        PortDef("in", "输入", True),
        PortDef("out", "输出", False),
    ],
}


@dataclass
class FlowNode:
    id: str
    node_type: NodeType
    x: float
    y: float
    properties: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(node_type: NodeType, x: float = 0, y: float = 0) -> "FlowNode":
        return FlowNode(
            id=uuid.uuid4().hex[:8],
            node_type=node_type,
            x=x,
            y=y,
            properties=FlowNode.default_properties(node_type),
        )

    @staticmethod
    def default_properties(node_type: NodeType) -> Dict[str, Any]:
        defaults = {
            NodeType.START: {},
            NodeType.OCR_SCAN: {"confidence": 0.5},
            NodeType.TEXT_MATCH: {"pattern": "", "is_regex": False},
            NodeType.CONDITION: {"variable": "", "operator": "==", "value": ""},
            NodeType.CLICK: {},
            NodeType.SET_VARIABLE: {"variable": "", "value": ""},
            NodeType.SCRIPT_REPLAY: {"script_name": ""},
            NodeType.WAIT: {"seconds": 1.0},
        }
        return dict(defaults.get(node_type, {}))

    def get_ports(self) -> List[PortDef]:
        return NODE_TYPE_PORTS.get(self.node_type, [])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.node_type.value,
            "x": self.x,
            "y": self.y,
            "properties": self.properties,
        }

    @staticmethod
    def from_dict(data: dict) -> "FlowNode":
        return FlowNode(
            id=data["id"],
            node_type=NodeType(data["type"]),
            x=data["x"],
            y=data["y"],
            properties=data.get("properties", {}),
        )


@dataclass
class FlowConnection:
    id: str
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str

    @staticmethod
    def create(src_node: str, src_port: str, tgt_node: str, tgt_port: str) -> "FlowConnection":
        return FlowConnection(
            id=uuid.uuid4().hex[:8],
            source_node_id=src_node,
            source_port_id=src_port,
            target_node_id=tgt_node,
            target_port_id=tgt_port,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_node": self.source_node_id,
            "source_port": self.source_port_id,
            "target_node": self.target_node_id,
            "target_port": self.target_port_id,
        }

    @staticmethod
    def from_dict(data: dict) -> "FlowConnection":
        return FlowConnection(
            id=data["id"],
            source_node_id=data["source_node"],
            source_port_id=data["source_port"],
            target_node_id=data["target_node"],
            target_port_id=data["target_port"],
        )


class FlowChart:
    """流程图 - 包含节点和连接的完整图结构"""

    def __init__(self):
        self.nodes: List[FlowNode] = []
        self.connections: List[FlowConnection] = []
        self.variables: Dict[str, Any] = {}

    def add_node(self, node: FlowNode):
        self.nodes.append(node)

    def remove_node(self, node_id: str):
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self.connections = [
            c
            for c in self.connections
            if c.source_node_id != node_id and c.target_node_id != node_id
        ]

    def add_connection(self, conn: FlowConnection):
        self.connections = [
            c
            for c in self.connections
            if not (c.target_node_id == conn.target_node_id and c.target_port_id == conn.target_port_id)
        ]
        self.connections.append(conn)

    def remove_connection(self, conn_id: str):
        self.connections = [c for c in self.connections if c.id != conn_id]

    def get_node(self, node_id: str) -> Optional[FlowNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_connections_from(self, node_id: str, port_id: str) -> List[FlowConnection]:
        return [
            c
            for c in self.connections
            if c.source_node_id == node_id and c.source_port_id == port_id
        ]

    def get_start_node(self) -> Optional[FlowNode]:
        for n in self.nodes:
            if n.node_type == NodeType.START:
                return n
        return None

    def save(self, filepath: str):
        data = {
            "version": "1.0",
            "nodes": [n.to_dict() for n in self.nodes],
            "connections": [c.to_dict() for c in self.connections],
            "variables": self.variables,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def load(filepath: str) -> "FlowChart":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        chart = FlowChart()
        chart.nodes = [FlowNode.from_dict(n) for n in data.get("nodes", [])]
        chart.connections = [FlowConnection.from_dict(c) for c in data.get("connections", [])]
        chart.variables = data.get("variables", {})
        return chart
