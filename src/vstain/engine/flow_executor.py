"""流程图执行引擎 - 将可视化流程图转换为可运行的脚本逻辑"""

import re
import time
from typing import Any, Dict, List, Optional

from gas.ocr_engine import OCREngine, OCRItem
from gas.recorder.operation_player import OperationPlayer

from src.vstain.models.flow_model import FlowChart, FlowNode, NodeType
from src.vstain.common.settings import SCRIPTS_DIR
from src.vstain.utils.logger import get_logger

log = get_logger()


class FlowExecutor:
    """
    执行流程图逻辑。

    每次调用 execute() 代表一个 "tick"（等同于原 home_widget.run() 的一次循环）。
    tick 间变量持久保留，OCR 结果每 tick 刷新。
    """

    def __init__(self, flow_chart: FlowChart, engine: OCREngine):
        self.chart = flow_chart
        self.engine = engine
        self.variables: Dict[str, Any] = dict(flow_chart.variables)
        self._player_cache: Dict[str, OperationPlayer] = {}

    def execute(self):
        """执行一次流程图遍历"""
        self._ocr_results: List[OCRItem] = []
        self._current_match: Optional[OCRItem] = None
        self._visited: set = set()

        start = self.chart.get_start_node()
        if not start:
            log.warning("流程图没有开始节点，跳过执行")
            return
        self._exec_node(start)

    # ---------- 节点分发 ----------
    def _exec_node(self, node: FlowNode):
        if node.id in self._visited:
            return
        self._visited.add(node.id)

        handler = {
            NodeType.START: self._handle_start,
            NodeType.OCR_SCAN: self._handle_ocr_scan,
            NodeType.TEXT_MATCH: self._handle_text_match,
            NodeType.CONDITION: self._handle_condition,
            NodeType.CLICK: self._handle_click,
            NodeType.SET_VARIABLE: self._handle_set_variable,
            NodeType.SCRIPT_REPLAY: self._handle_script_replay,
            NodeType.WAIT: self._handle_wait,
        }.get(node.node_type)
        if handler:
            handler(node)

    def _follow(self, node: FlowNode, port_id: str):
        """沿指定输出端口继续执行下游节点"""
        for conn in self.chart.get_connections_from(node.id, port_id):
            target = self.chart.get_node(conn.target_node_id)
            if target:
                self._exec_node(target)

    # ---------- 各节点处理器 ----------
    def _handle_start(self, node: FlowNode):
        self._follow(node, "out")

    def _handle_ocr_scan(self, node: FlowNode):
        confidence = float(node.properties.get("confidence", 0.5))
        self._ocr_results = self.engine._perform_ocr(confidence=confidence)
        log.debug(f"OCR 扫描完成, 共 {len(self._ocr_results)} 条结果")
        self._follow(node, "out")

    def _handle_text_match(self, node: FlowNode):
        pattern = node.properties.get("pattern", "")
        is_regex = node.properties.get("is_regex", False)
        if not pattern:
            self._follow(node, "not_matched")
            return

        matched = False
        for item in self._ocr_results:
            text = item.text
            if is_regex:
                if re.search(pattern, text):
                    matched = True
                    self._current_match = item
                    break
            else:
                if pattern in text:
                    matched = True
                    self._current_match = item
                    break

        if matched:
            log.debug(f"文本匹配成功: '{pattern}' -> '{self._current_match.text}'")
            self._follow(node, "matched")
        else:
            self._follow(node, "not_matched")

    def _handle_condition(self, node: FlowNode):
        var_name = node.properties.get("variable", "")
        operator = node.properties.get("operator", "==")
        value_str = node.properties.get("value", "")
        actual = self.variables.get(var_name)

        result = self._evaluate_condition(actual, operator, value_str)
        log.debug(f"条件判断: {var_name}({actual}) {operator} {value_str} => {result}")
        self._follow(node, "true" if result else "false")

    def _handle_click(self, node: FlowNode):
        if self._current_match:
            x, y = self._current_match.center
            self.engine.click(x, y)
            log.debug(f"点击: ({x}, {y})")
        self._follow(node, "out")

    def _handle_set_variable(self, node: FlowNode):
        var_name = node.properties.get("variable", "")
        raw = node.properties.get("value", "")
        if var_name:
            self.variables[var_name] = self._cast_value(raw)
            log.debug(f"设置变量: {var_name} = {self.variables[var_name]}")
        self._follow(node, "out")

    def _handle_script_replay(self, node: FlowNode):
        script_name = node.properties.get("script_name", "")
        if script_name:
            path = SCRIPTS_DIR / script_name
            if path.exists():
                if script_name not in self._player_cache:
                    player = OperationPlayer(self.engine.device)
                    player.load_from_file(str(path))
                    self._player_cache[script_name] = player
                self._player_cache[script_name].replay()
                log.debug(f"脚本回放: {script_name}")
            else:
                log.warning(f"脚本文件不存在: {path}")
        self._follow(node, "out")

    def _handle_wait(self, node: FlowNode):
        seconds = float(node.properties.get("seconds", 1.0))
        time.sleep(seconds)
        self._follow(node, "out")

    # ---------- 辅助 ----------
    @staticmethod
    def _cast_value(raw: str) -> Any:
        if raw.lower() == "true":
            return True
        if raw.lower() == "false":
            return False
        try:
            return float(raw)
        except ValueError:
            return raw

    @staticmethod
    def _evaluate_condition(actual: Any, operator: str, value_str: str) -> bool:
        try:
            a = float(actual) if actual is not None else 0.0
            b = float(value_str) if value_str else 0.0
            return {
                "==": a == b,
                "!=": a != b,
                ">": a > b,
                "<": a < b,
                ">=": a >= b,
                "<=": a <= b,
            }.get(operator, False)
        except (ValueError, TypeError):
            a = str(actual) if actual is not None else ""
            return {"==": a == value_str, "!=": a != value_str}.get(operator, False)
