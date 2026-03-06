"""流程图执行引擎 - 将可视化流程图转换为可运行的脚本逻辑

支持循环（LOOP 节点 + 回边），用全局步数上限防止死循环。
"""

import re
import time
from typing import Any, Dict, List, Optional

from gas.ocr_engine import OCREngine, OCRItem
from gas.recorder.operation_player import OperationPlayer

from src.vstain.models.flow_model import FlowChart, FlowNode, NodeType
from src.vstain.common.settings import SCRIPTS_DIR
from src.vstain.utils.logger import get_logger

log = get_logger()

MAX_STEPS = 500


class FlowExecutor:
    """
    执行流程图逻辑。

    每次 execute() 代表一个 tick。
    tick 间 `variables` 持久保留，OCR 结果和循环计数器每 tick 刷新。
    全局步数上限 MAX_STEPS 防止意外死循环。
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
        self._step_count = 0
        self._loop_state: Dict[str, int] = {}

        start = self.chart.get_start_node()
        if not start:
            log.warning("流程图没有开始节点，跳过执行")
            return
        self._exec_node(start)

    # ---------- 节点分发 ----------
    def _exec_node(self, node: FlowNode):
        self._step_count += 1
        if self._step_count > MAX_STEPS:
            log.warning(f"执行步数超过 {MAX_STEPS}，强制终止（可能存在死循环）")
            return

        handler = {
            NodeType.START: self._handle_start,
            NodeType.OCR_SCAN: self._handle_ocr_scan,
            NodeType.TEXT_MATCH: self._handle_text_match,
            NodeType.CONDITION: self._handle_condition,
            NodeType.LOOP: self._handle_loop,
            NodeType.CLICK: self._handle_click,
            NodeType.SET_VARIABLE: self._handle_set_variable,
            NodeType.SCRIPT_REPLAY: self._handle_script_replay,
            NodeType.WAIT: self._handle_wait,
            NodeType.LOG: self._handle_log,
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

    def _handle_loop(self, node: FlowNode):
        max_iter = int(node.properties.get("max_iterations", -1))
        counter_var = node.properties.get("counter_variable", "")

        key = f"_loop_{node.id}"
        count = self._loop_state.get(key, 0)
        self._loop_state[key] = count + 1

        if counter_var:
            self.variables[counter_var] = count

        if 0 <= max_iter <= count:
            self._loop_state.pop(key, None)
            log.debug(f"循环结束: 已执行 {count} 次")
            self._follow(node, "done")
        else:
            log.debug(f"循环第 {count + 1} 次 (max={max_iter})")
            self._follow(node, "body")

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

    def _handle_log(self, node: FlowNode):
        msg = node.properties.get("message", "")
        resolved = self._resolve_template(msg)
        log.info(f"[流程日志] {resolved}")
        self._follow(node, "out")

    # ---------- 辅助 ----------
    def _resolve_template(self, template: str) -> str:
        """将 {var_name} 替换为变量值"""
        import re as _re
        def _repl(m):
            name = m.group(1)
            return str(self.variables.get(name, f"{{{name}}}"))
        return _re.sub(r"\{(\w+)\}", _repl, template)

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
