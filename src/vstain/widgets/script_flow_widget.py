"""脚本流程编排页面

包含: 工具栏(节点创建 + 操作按钮) / 画布 / 属性面板 / 变量监视 / 小地图 / 调试
"""

import json
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFileDialog,
    QFormLayout,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    LineEdit,
    ToolButton,
    SwitchButton,
    ComboBox,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    DoubleSpinBox,
    SpinBox,
    SingleDirectionScrollArea,
    TextEdit,
)

from gas.ocr_engine import OCREngine
from src.vstain.engine.flow_executor import FlowExecutor
from src.vstain.common.config import cfg
from src.vstain.common.cons import SPECIAL_KEY_MAP

from src.vstain.models.flow_model import (
    FlowChart,
    FlowNode,
    NodeType,
    NODE_TYPE_LABELS,
    NODE_TYPE_COLORS,
)
from src.vstain.components.flow_editor import (
    FlowScene,
    FlowCanvas,
    FlowMinimap,
)
from src.vstain.components.themed_splitter import ThemedSplitter
from src.vstain.common.settings import FLOWS_DIR, SCRIPTS_DIR

FLOWS_DIR.mkdir(parents=True, exist_ok=True)

_TOOLBAR_NODES = [
    (NodeType.START, FluentIcon.PLAY),
    (NodeType.OCR_SCAN, FluentIcon.SEARCH),
    (NodeType.TEXT_MATCH, FluentIcon.FONT),
    (NodeType.CONDITION, FluentIcon.FILTER),
    (NodeType.LOOP, FluentIcon.SYNC),
    (NodeType.CLICK, FluentIcon.FINGERPRINT),
    (NodeType.SET_VARIABLE, FluentIcon.EDIT),
    (NodeType.SCRIPT_REPLAY, FluentIcon.VIDEO),
    (NodeType.KEY_INPUT, FluentIcon.BOOK_SHELF),
    (NodeType.SWIPE, FluentIcon.SCROLL),
    (NodeType.WAIT, FluentIcon.HISTORY),
    (NodeType.LOG, FluentIcon.MESSAGE),
    (NodeType.COMMENT, FluentIcon.CHAT),
    (NodeType.SUBFLOW, FluentIcon.COMMAND_PROMPT),
]


# ================================================================
#  按键捕获按钮
# ================================================================
class _KeyCaptureButton(PushButton):
    key_captured = pyqtSignal(str)

    def __init__(self, current_key="", parent=None):
        super().__init__(parent)
        self._current_key = current_key
        self._listening = False
        self._update_text()
        self.clicked.connect(self._start_listening)

    def _update_text(self):
        self.setText(self._current_key if self._current_key else "点击录入按键...")

    def _start_listening(self):
        self._listening = True
        self.setText("按下任意键...")
        self.grabKeyboard()

    def keyPressEvent(self, event):
        if not self._listening:
            super().keyPressEvent(event)
            return
        kc = SPECIAL_KEY_MAP.get(event.key())
        if kc is not None:
            self._current_key = kc.name
            self._listening = False
            self.releaseKeyboard()
            self._update_text()
            self.key_captured.emit(self._current_key)
        else:
            self.setText("不支持该键，再试...")

    def focusOutEvent(self, event):
        if self._listening:
            self._listening = False
            self.releaseKeyboard()
            self._update_text()
        super().focusOutEvent(event)


# ================================================================
#  属性面板
# ================================================================
class _PropertiesPanel(SingleDirectionScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(240)
        self.setMaximumWidth(340)
        self._node = None
        self._inner = QWidget()
        self._layout = QFormLayout(self._inner)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(6)
        self.setWidget(self._inner)
        self.enableTransparentBackground()
        self._show_empty()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_empty(self):
        self._clear()
        lbl = BodyLabel("选中节点以编辑属性")
        lbl.setAlignment(Qt.AlignCenter)
        self._layout.addRow(lbl)

    def show_node(self, node: FlowNode):
        self._node = node
        self._clear()
        title = BodyLabel(NODE_TYPE_LABELS[node.node_type])
        title.setAlignment(Qt.AlignCenter)
        self._layout.addRow(title)
        self._build(node)

    def hide_node(self):
        self._node = None
        self._show_empty()

    def _build(self, n: FlowNode):
        nt = n.node_type
        p = n.properties
        if nt == NodeType.OCR_SCAN:
            self._add_float("confidence", "置信度", p, 0.0, 1.0, 0.1)
        elif nt == NodeType.TEXT_MATCH:
            self._add_line("pattern", "匹配文本", p)
            self._add_switch("is_regex", "正则匹配", p)
        elif nt == NodeType.CONDITION:
            self._add_line("variable", "变量名", p)
            self._add_combo("operator", "运算符", p, ["==", "!=", ">", "<", ">=", "<="])
            self._add_line("value", "值", p)
        elif nt == NodeType.LOOP:
            self._add_int("max_iterations", "最大次数(-1=无限)", p, -1, 99999)
            self._add_line("counter_variable", "计数变量", p)
        elif nt == NodeType.CLICK:
            self._add_switch("use_ocr_result", "使用 OCR 坐标", p)
            self._add_float("x", "X", p, 0, 9999, 1)
            self._add_float("y", "Y", p, 0, 9999, 1)
        elif nt == NodeType.SET_VARIABLE:
            self._add_line("variable", "变量名", p)
            self._add_line("value", "值", p)
        elif nt == NodeType.SCRIPT_REPLAY:
            script_name_list = [p.name for p in SCRIPTS_DIR.iterdir() if p.suffix.lower() == ".json"]
            self._add_combo("script_name", "脚本文件", p, script_name_list)
        elif nt == NodeType.KEY_INPUT:
            self._add_key_capture("key", "按键", p)
            self._add_combo("action", "动作", p, ["tap", "down", "up"])
        elif nt == NodeType.SWIPE:
            self._add_int("x1", "起点X", p, 0, 9999)
            self._add_int("y1", "起点Y", p, 0, 9999)
            self._add_int("x2", "终点X", p, 0, 9999)
            self._add_int("y2", "终点Y", p, 0, 9999)
            self._add_float("duration", "持续(秒)", p, 0.01, 10, 0.1)
        elif nt == NodeType.WAIT:
            self._add_float("seconds", "秒数", p, 0.1, 600, 0.5)
        elif nt == NodeType.LOG:
            self._add_line("message", "日志({var}模板)", p)
        elif nt == NodeType.COMMENT:
            self._add_line("text", "注释内容", p)
        elif nt == NodeType.SUBFLOW:
            self._add_line("flow_file", "流程图文件名", p)

    # ---------- 控件工厂 ----------
    def _add_line(self, key, label, props):
        w = LineEdit()
        w.setText(str(props.get(key, "")))
        w.textChanged.connect(lambda t, k=key: self._set(k, t))
        self._layout.addRow(BodyLabel(label), w)

    def _add_switch(self, key, label, props):
        w = SwitchButton()
        w.setChecked(bool(props.get(key, False)))
        w.checkedChanged.connect(lambda c, k=key: self._set(k, c))
        self._layout.addRow(BodyLabel(label), w)

    def _add_combo(self, key, label, props, items):
        w = ComboBox()
        w.addItems(items)
        w.currentTextChanged.connect(lambda t, k=key: self._set(k, t))
        w.setCurrentText(str(props.get(key, items[0])))
        self._layout.addRow(BodyLabel(label), w)

    def _add_float(self, key, label, props, lo, hi, step):
        w = DoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setValue(float(props.get(key, lo)))
        w.valueChanged.connect(lambda v, k=key: self._set(k, v))
        self._layout.addRow(BodyLabel(label), w)

    def _add_int(self, key, label, props, lo=0, hi=99999):
        w = SpinBox()
        w.setRange(lo, hi)
        w.setValue(int(props.get(key, lo)))
        w.valueChanged.connect(lambda v, k=key: self._set(k, v))
        self._layout.addRow(BodyLabel(label), w)

    def _add_key_capture(self, key, label, props):
        w = _KeyCaptureButton(str(props.get(key, "")))
        w.key_captured.connect(lambda name, k=key: self._set(k, name))
        self._layout.addRow(BodyLabel(label), w)

    def _set(self, key, val):
        if self._node:
            self._node.properties[key] = val


# ================================================================
#  变量监视面板
# ================================================================
class _VariableWatch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)
        title = BodyLabel("变量监视")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        self._text = TextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumHeight(140)
        lay.addWidget(self._text)

    def update_variables(self, variables: dict):
        lines = [f"{k} = {v}" for k, v in variables.items()]
        self._text.setPlainText("\n".join(lines) if lines else "(无变量)")


# ================================================================
#  调试线程
# ================================================================
class _DebugThread(QThread):
    node_highlight = pyqtSignal(str)
    variables_updated = pyqtSignal(dict)
    debug_finished = pyqtSignal()
    debug_error = pyqtSignal(str)

    def __init__(self, chart: FlowChart, parent=None):
        super().__init__(parent)
        self._chart = chart
        self._stop_flag = False
        self._executor: FlowExecutor | None = None

    def request_stop(self):
        self._stop_flag = True
        if self._executor:
            self._executor.request_stop()

    def run(self):
        try:
            engine = OCREngine.create_with_window(
                cfg.get(cfg.hwndWindowsTitle),
                cfg.get(cfg.hwndClassname),
                2,
                False,
            )
            executor = FlowExecutor(
                self._chart,
                engine,
                node_callback=self._on_node,
                step_delay=0.35,
            )
            self._executor = executor
            executor.execute()
            self.variables_updated.emit(dict(executor.variables))
        except Exception as e:
            self.debug_error.emit(str(e))
        finally:
            self._executor = None
            self.debug_finished.emit()

    def _on_node(self, node_id: str):
        if self._stop_flag:
            raise InterruptedError("调试已手动停止")
        self.node_highlight.emit(node_id)
        if self._executor:
            self.variables_updated.emit(dict(self._executor.variables))


# ================================================================
#  主页面
# ================================================================
class ScriptFlowWidget(QWidget):
    def __init__(self, objectName: str, parent=None):
        super().__init__(parent)
        self.setObjectName(objectName)
        self._scene = FlowScene()
        self._canvas = FlowCanvas(self._scene, self)
        self._minimap = FlowMinimap(self._scene, self._canvas, self._canvas)
        self._props = _PropertiesPanel()
        self._varwatch = _VariableWatch()
        self._debug_thread: _DebugThread | None = None
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工具栏 ----
        tb = QWidget()
        tb.setFixedHeight(46)
        tblay = QHBoxLayout(tb)
        tblay.setContentsMargins(8, 4, 8, 4)
        tblay.setSpacing(4)

        for nt, icon in _TOOLBAR_NODES:
            b = ToolButton(icon)
            b.setFixedSize(QSize(34, 34))
            b.setToolTip(NODE_TYPE_LABELS[nt])
            b.clicked.connect(lambda chk, _n=nt: self._scene.add_node(_n))
            tblay.addWidget(b)

        tblay.addStretch()

        for icon, tip, fn in [
            (FluentIcon.LAYOUT, "自动布局", self._auto_layout),
            (FluentIcon.PHOTO, "导出图片", self._export_image),
        ]:
            b = ToolButton(icon)
            b.setFixedSize(QSize(34, 34))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tblay.addWidget(b)

        for icon, tip, fn in [
            (FluentIcon.LEFT_ARROW, "撤销 Ctrl+Z", self._scene.undo),
            (FluentIcon.RIGHT_ARROW, "重做 Ctrl+Y", self._scene.redo),
        ]:
            b = ToolButton(icon)
            b.setFixedSize(QSize(34, 34))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tblay.addWidget(b)

        self._debug_btn = PrimaryPushButton("调试运行")
        self._debug_btn.setFixedSize(QSize(80, 30))
        self._debug_btn.setToolTip("使用当前流程图执行一次并高亮节点路径")
        tblay.addWidget(self._debug_btn)

        self._stop_debug_btn = ToolButton(FluentIcon.CLOSE)
        self._stop_debug_btn.setFixedSize(QSize(34, 34))
        self._stop_debug_btn.setToolTip("停止调试")
        self._stop_debug_btn.setVisible(False)
        tblay.addWidget(self._stop_debug_btn)

        tblay.addStretch()

        for icon, tip, fn in [
            (FluentIcon.SAVE, "保存", self._save),
            (FluentIcon.FOLDER, "加载", self._load),
            (FluentIcon.DELETE, "清空", self._clear),
        ]:
            b = ToolButton(icon)
            b.setFixedSize(QSize(34, 34))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tblay.addWidget(b)

        root.addWidget(tb)

        # ---- 主体 ----
        splitter = ThemedSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._canvas)

        right = QWidget()
        right.setMinimumWidth(240)
        right.setMaximumWidth(340)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._props, 1)
        rl.addWidget(self._varwatch, 0)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root.addWidget(splitter, 1)

    def _setup_connections(self):
        self._scene.node_selected.connect(self._on_select)
        self._scene.flow_changed.connect(self._refresh_minimap)
        self._debug_btn.clicked.connect(self._start_debug)
        self._stop_debug_btn.clicked.connect(self._stop_debug)

    def _on_select(self, node):
        if node:
            self._props.show_node(node)
        else:
            self._props.hide_node()

    def _refresh_minimap(self):
        self._minimap.refresh()
        self._minimap.reposition()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._minimap.reposition()

    # ---------- 操作 ----------
    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存流程图", str(FLOWS_DIR), "JSON (*.json)"
        )
        if path:
            self._scene.flow_chart.save(path)
            InfoBar.success(
                "成功", f"已保存: {Path(path).name}", parent=self, duration=2000
            )

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载流程图", str(FLOWS_DIR), "JSON (*.json)"
        )
        if path:
            chart = FlowChart.load(path)
            self._scene.load_flow_chart(chart)
            InfoBar.success(
                "成功", f"已加载: {Path(path).name}", parent=self, duration=2000
            )

    def _clear(self):
        self._scene.load_flow_chart(FlowChart())

    def _auto_layout(self):
        self._scene.auto_layout()

    def _export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出图片", "", "PNG (*.png);;JPEG (*.jpg)"
        )
        if path:
            self._scene.export_image(path)
            InfoBar.success(
                "成功", f"已导出: {Path(path).name}", parent=self, duration=2000
            )

    def update_variable_watch(self, variables: dict):
        self._varwatch.update_variables(variables)

    # ---------- 调试 ----------
    def _start_debug(self):
        chart = self._scene.flow_chart
        if not chart.get_start_node():
            InfoBar.warning(
                "提示", "流程图中没有 开始 节点", parent=self, duration=2000
            )
            return
        self._debug_btn.setEnabled(False)
        self._stop_debug_btn.setVisible(True)
        InfoBar.info("调试", "正在初始化 OCR 引擎并执行…", parent=self, duration=2000)

        t = _DebugThread(chart, self)
        t.node_highlight.connect(self._on_debug_node, Qt.QueuedConnection)
        t.variables_updated.connect(self._on_debug_vars, Qt.QueuedConnection)
        t.debug_finished.connect(self._on_debug_done, Qt.QueuedConnection)
        t.debug_error.connect(self._on_debug_error, Qt.QueuedConnection)
        self._debug_thread = t
        t.start()

    def _stop_debug(self):
        if self._debug_thread and self._debug_thread.isRunning():
            self._debug_thread.request_stop()

    @pyqtSlot(str)
    def _on_debug_node(self, node_id: str):
        self._scene.highlight_node(node_id)

    @pyqtSlot(dict)
    def _on_debug_vars(self, variables: dict):
        self._varwatch.update_variables(variables)

    @pyqtSlot()
    def _on_debug_done(self):
        self._scene.clear_highlight()
        self._debug_btn.setEnabled(True)
        self._stop_debug_btn.setVisible(False)
        self._debug_thread = None
        InfoBar.success("调试", "执行完毕", parent=self, duration=2000)

    @pyqtSlot(str)
    def _on_debug_error(self, msg: str):
        if "手动停止" not in msg:
            InfoBar.error("调试出错", msg, parent=self, duration=4000)
