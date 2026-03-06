"""脚本流程图编辑器页面 - 工具栏 + 画布 + 属性面板"""

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFileDialog,
    QSplitter,
)
from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    FluentIcon,
    BodyLabel,
    ComboBox,
    LineEdit,
    SwitchButton,
    InfoBar,
    InfoBarPosition,
    ToolButton,
    DoubleSpinBox,
)

from src.vstain.models.flow_model import FlowChart, FlowNode, NodeType, NODE_TYPE_LABELS
from src.vstain.components.flow_editor import FlowScene, FlowCanvas
from src.vstain.common.settings import SCRIPTS_DIR, RESOURCE_DIR
from src.vstain.utils.logger import get_logger

log = get_logger()

FLOWS_DIR = RESOURCE_DIR / "flows"

# 工具栏中按钮对应的节点类型及图标
_TOOLBAR_NODES = [
    (NodeType.START, FluentIcon.PLAY_SOLID),
    (NodeType.OCR_SCAN, FluentIcon.SEARCH),
    (NodeType.TEXT_MATCH, FluentIcon.FONT),
    (NodeType.CONDITION, FluentIcon.FILTER),
    (NodeType.CLICK, FluentIcon.FINGERPRINT),
    (NodeType.SET_VARIABLE, FluentIcon.EDIT),
    (NodeType.SCRIPT_REPLAY, FluentIcon.VIDEO),
    (NodeType.WAIT, FluentIcon.STOP_WATCH),
]


# ================================================================
#  属性面板
# ================================================================
class _PropertiesPanel(QWidget):
    """右侧节点属性编辑面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self._node: Optional[FlowNode] = None
        self._setup_ui()

    def _setup_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(12, 12, 12, 12)
        self._root.setSpacing(8)

        self._title = BodyLabel("属性面板")
        self._title.setAlignment(Qt.AlignCenter)
        self._root.addWidget(self._title)

        self._props_container = QWidget()
        self._props_layout = QVBoxLayout(self._props_container)
        self._props_layout.setContentsMargins(0, 0, 0, 0)
        self._props_layout.setSpacing(6)
        self._root.addWidget(self._props_container)

        self._root.addStretch()

    # ---------- 公开 ----------
    def set_node(self, node: Optional[FlowNode]):
        self._node = node
        self._clear_props()
        if node is None:
            self._title.setText("未选择节点")
            return
        self._title.setText(NODE_TYPE_LABELS[node.node_type])
        self._build_editors(node)

    # ---------- 构建编辑器 ----------
    def _build_editors(self, node: FlowNode):
        nt = node.node_type
        if nt == NodeType.TEXT_MATCH:
            self._add_line("匹配文本", "pattern", node)
            self._add_switch("正则表达式", "is_regex", node)
        elif nt == NodeType.CONDITION:
            self._add_line("变量名", "variable", node)
            self._add_combo(
                "运算符", "operator", ["==", "!=", ">", "<", ">=", "<="], node
            )
            self._add_line("比较值", "value", node)
        elif nt == NodeType.SET_VARIABLE:
            self._add_line("变量名", "variable", node)
            self._add_line("值", "value", node)
        elif nt == NodeType.SCRIPT_REPLAY:
            self._add_combo("脚本文件", "script_name", self._script_list(), node)
        elif nt == NodeType.WAIT:
            self._add_spin("等待秒数", "seconds", node, 0.1, 60.0)
        elif nt == NodeType.OCR_SCAN:
            self._add_spin("置信度", "confidence", node, 0.1, 1.0)

    # ---------- 控件工厂 ----------
    def _add_line(self, label: str, key: str, node: FlowNode):
        lbl = BodyLabel(label)
        edit = LineEdit()
        edit.setText(str(node.properties.get(key, "")))
        edit.textChanged.connect(lambda t, k=key: self._set_prop(k, t))
        self._props_layout.addWidget(lbl)
        self._props_layout.addWidget(edit)

    def _add_combo(self, label: str, key: str, items: list, node: FlowNode):
        lbl = BodyLabel(label)
        cb = ComboBox()
        cb.addItems(items)
        cur = str(node.properties.get(key, ""))
        if cur in items:
            cb.setCurrentText(cur)
        cb.currentTextChanged.connect(lambda t, k=key: self._set_prop(k, t))
        self._props_layout.addWidget(lbl)
        self._props_layout.addWidget(cb)

    def _add_switch(self, label: str, key: str, node: FlowNode):
        lbl = BodyLabel(label)
        sw = SwitchButton()
        sw.setChecked(bool(node.properties.get(key, False)))
        sw.checkedChanged.connect(lambda c, k=key: self._set_prop(k, c))
        self._props_layout.addWidget(lbl)
        self._props_layout.addWidget(sw)

    def _add_spin(self, label: str, key: str, node: FlowNode, lo: float, hi: float):
        lbl = BodyLabel(label)
        sb = DoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setSingleStep(0.1)
        sb.setDecimals(2)
        sb.setValue(float(node.properties.get(key, lo)))
        sb.valueChanged.connect(lambda v, k=key: self._set_prop(k, v))
        self._props_layout.addWidget(lbl)
        self._props_layout.addWidget(sb)

    # ---------- 辅助 ----------
    def _set_prop(self, key: str, value):
        if self._node:
            self._node.properties[key] = value

    def _clear_props(self):
        while self._props_layout.count():
            item = self._props_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    @staticmethod
    def _script_list() -> list:
        if not SCRIPTS_DIR.is_dir():
            return []
        return [p.name for p in SCRIPTS_DIR.iterdir() if p.suffix.lower() == ".json"]


# ================================================================
#  页面主 Widget
# ================================================================
class ScriptFlowWidget(QWidget):
    """脚本流程图编辑器 - 作为主窗口的一个子页面"""

    def __init__(self, objectName: str, parent=None):
        super().__init__(parent)
        self.setObjectName(objectName)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工具栏 ----
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 6, 10, 6)
        tb_layout.setSpacing(6)

        for nt, icon in _TOOLBAR_NODES:
            btn = ToolButton(icon)
            btn.setToolTip(f"添加 {NODE_TYPE_LABELS[nt]}")
            btn.setFixedSize(36, 36)
            btn.clicked.connect(lambda checked, _nt=nt: self._add_node(_nt))
            tb_layout.addWidget(btn)

        tb_layout.addStretch()

        self._save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存")
        self._save_btn.setFixedWidth(80)
        tb_layout.addWidget(self._save_btn)

        self._load_btn = PushButton(FluentIcon.FOLDER, "加载")
        self._load_btn.setFixedWidth(80)
        tb_layout.addWidget(self._load_btn)

        self._clear_btn = PushButton(FluentIcon.DELETE, "清空")
        self._clear_btn.setFixedWidth(80)
        tb_layout.addWidget(self._clear_btn)

        root.addWidget(toolbar)

        # ---- 画布 + 属性面板 ----
        splitter = QSplitter(Qt.Horizontal)

        self._scene = FlowScene()
        self._canvas = FlowCanvas(self._scene)
        splitter.addWidget(self._canvas)

        self._props = _PropertiesPanel()
        splitter.addWidget(self._props)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root.addWidget(splitter)

    def _connect_signals(self):
        self._scene.node_selected.connect(self._on_node_selected)
        self._save_btn.clicked.connect(self._save)
        self._load_btn.clicked.connect(self._load)
        self._clear_btn.clicked.connect(self._clear)

    # ---------- 操作 ----------
    def _add_node(self, node_type: NodeType):
        center = self._canvas.mapToScene(self._canvas.viewport().rect().center())
        self._scene.add_node(node_type, center.x(), center.y())

    def _on_node_selected(self, node):
        self._props.set_node(node)
        if node:
            node_item = self._scene.node_items.get(node.id)
            if node_item:
                node_item.update()

    def _save(self):
        FLOWS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存流程图", str(FLOWS_DIR), "JSON (*.json)"
        )
        if path:
            self._scene.flow_chart.save(path)
            InfoBar.success(
                "成功", "流程图已保存", parent=self, position=InfoBarPosition.TOP
            )
            log.info(f"流程图已保存: {path}")

    def _load(self):
        FLOWS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "加载流程图", str(FLOWS_DIR), "JSON (*.json)"
        )
        if path:
            try:
                chart = FlowChart.load(path)
                self._scene.load_flow_chart(chart)
                self._props.set_node(None)
                InfoBar.success(
                    "成功", "流程图已加载", parent=self, position=InfoBarPosition.TOP
                )
                log.info(f"流程图已加载: {path}")
            except Exception as e:
                log.error(f"加载流程图失败: {e}")
                InfoBar.error(
                    "错误", f"加载失败: {e}", parent=self, position=InfoBarPosition.TOP
                )

    def _clear(self):
        self._scene.load_flow_chart(FlowChart())
        self._props.set_node(None)

    @property
    def flow_chart(self) -> FlowChart:
        return self._scene.flow_chart
