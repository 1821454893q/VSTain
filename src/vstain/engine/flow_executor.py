"""流程图执行引擎

支持循环 / 条件 / 键盘输入 / 滑动 / 子流程 / 日志 / 调试回调。
全局步数上限 MAX_STEPS 防止死循环。
"""

import re
import time
from typing import Any, Callable, Dict, List, Optional

from gas.ocr_engine import OCREngine, OCRItem
from gas.recorder.operation_player import OperationPlayer
from gas.cons.key_code import KeyCode

from src.vstain.models.flow_model import FlowChart, FlowNode, NodeType
from src.vstain.common.settings import SCRIPTS_DIR, FLOWS_DIR
from src.vstain.utils.logger import get_logger

log = get_logger()

MAX_STEPS = 500


class FlowExecutor:
    """
    每次 execute() 代表一个 tick。
    tick 间 variables 持久保留，OCR 结果和循环计数器每 tick 刷新。
    """

    def __init__(
        self,
        flow_chart: FlowChart,
        engine: OCREngine,
        node_callback: Optional[Callable[[str], None]] = None,
        step_delay: float = 0.0,
    ):
        self.chart = flow_chart
        self.engine = engine
        self.variables: Dict[str, Any] = dict(flow_chart.variables)
        self._player_cache: Dict[str, OperationPlayer] = {}
        self._node_callback = node_callback
        self.step_delay = step_delay
        self._stop_flag = False

    def request_stop(self):
        self._stop_flag = True

    def execute(self):
        self._stop_flag = False
        self._ocr_results: List[OCRItem] = []
        self._current_match: Optional[OCRItem] = None
        self._step_count = 0
        self._loop_state: Dict[str, int] = {}

        start = self.chart.get_start_node()
        if not start:
            log.warning("流程图没有开始节点，跳过执行")
            return
        self._exec_node(start)

    def _exec_node(self, node: FlowNode):
        if self._stop_flag:
            raise InterruptedError("执行已停止")
        self._step_count += 1
        if self._step_count > MAX_STEPS:
            log.warning(f"执行步数超过 {MAX_STEPS}，强制终止")
            return
        if self._node_callback:
            self._node_callback(node.id)
        if self.step_delay > 0:
            time.sleep(self.step_delay)

        _H = {
            NodeType.START: self._h_start,
            NodeType.OCR_SCAN: self._h_ocr,
            NodeType.TEXT_MATCH: self._h_match,
            NodeType.CONDITION: self._h_cond,
            NodeType.LOOP: self._h_loop,
            NodeType.CLICK: self._h_click,
            NodeType.SET_VARIABLE: self._h_setvar,
            NodeType.SCRIPT_REPLAY: self._h_replay,
            NodeType.KEY_INPUT: self._h_key,
            NodeType.SWIPE: self._h_swipe,
            NodeType.WAIT: self._h_wait,
            NodeType.LOG: self._h_log,
            NodeType.COMMENT: self._h_comment,
            NodeType.SUBFLOW: self._h_subflow,
        }
        handler = _H.get(node.node_type)
        if handler:
            handler(node)

    def _follow(self, node: FlowNode, port_id: str):
        for conn in self.chart.get_connections_from(node.id, port_id):
            target = self.chart.get_node(conn.target_node_id)
            if target:
                self._exec_node(target)

    # ---------- 处理器 ----------
    def _h_start(self, n):
        self._follow(n, "out")

    def _h_ocr(self, n):
        conf = float(n.properties.get("confidence", 0.5))
        self._ocr_results = self.engine._perform_ocr(confidence=conf)
        log.debug(f"OCR 扫描完成, 共 {len(self._ocr_results)} 条")
        self._follow(n, "out")

    def _h_match(self, n):
        pattern = n.properties.get("pattern", "")
        is_re = n.properties.get("is_regex", False)
        if not pattern:
            self._follow(n, "not_matched"); return
        for item in self._ocr_results:
            hit = (re.search(pattern, item.text) if is_re else pattern in item.text)
            if hit:
                self._current_match = item
                log.debug(f"匹配: '{pattern}' -> '{item.text}'")
                self._follow(n, "matched"); return
        self._follow(n, "not_matched")

    def _h_cond(self, n):
        var = n.properties.get("variable", "")
        op = n.properties.get("operator", "==")
        val = n.properties.get("value", "")
        actual = self.variables.get(var)
        r = self._eval(actual, op, val)
        log.debug(f"条件: {var}({actual}) {op} {val} => {r}")
        self._follow(n, "true" if r else "false")

    def _h_loop(self, n):
        mx = int(n.properties.get("max_iterations", -1))
        cv = n.properties.get("counter_variable", "")
        key = f"_loop_{n.id}"
        cnt = self._loop_state.get(key, 0)
        self._loop_state[key] = cnt + 1
        if cv:
            self.variables[cv] = cnt
        if 0 <= mx <= cnt:
            self._loop_state.pop(key, None)
            log.debug(f"循环结束, 共 {cnt} 次")
            self._follow(n, "done")
        else:
            self._follow(n, "body")

    def _h_click(self, n):
        if self._current_match:
            x, y = self._current_match.center
            self.engine.click(x, y)
            log.debug(f"点击: ({x},{y})")
        self._follow(n, "out")

    def _h_setvar(self, n):
        var = n.properties.get("variable", "")
        raw = n.properties.get("value", "")
        if var:
            self.variables[var] = self._cast(raw)
            log.debug(f"设置: {var}={self.variables[var]}")
        self._follow(n, "out")

    def _h_replay(self, n):
        name = n.properties.get("script_name", "")
        if name:
            p = SCRIPTS_DIR / name
            if p.exists():
                if name not in self._player_cache:
                    pl = OperationPlayer(self.engine.device)
                    pl.load_from_file(str(p))
                    self._player_cache[name] = pl
                self._player_cache[name].replay()
                log.debug(f"回放: {name}")
            else:
                log.warning(f"脚本不存在: {p}")
        self._follow(n, "out")

    def _h_key(self, n):
        key_name = n.properties.get("key", "")
        action = n.properties.get("action", "tap")
        if key_name:
            try:
                kc = KeyCode[key_name]
            except KeyError:
                log.warning(f"未知按键: {key_name}")
                self._follow(n, "out"); return
            if action == "tap":
                self.engine.key_click(kc)
            elif action == "down":
                self.engine.key_down(kc)
            elif action == "up":
                self.engine.key_up(kc)
            log.debug(f"按键: {key_name} {action}")
        self._follow(n, "out")

    def _h_swipe(self, n):
        x1 = int(n.properties.get("x1", 0))
        y1 = int(n.properties.get("y1", 0))
        x2 = int(n.properties.get("x2", 0))
        y2 = int(n.properties.get("y2", 0))
        dur = float(n.properties.get("duration", 0.5))
        self.engine.swipe(x1, y1, x2, y2, duration=dur)
        log.debug(f"滑动: ({x1},{y1})->({x2},{y2})")
        self._follow(n, "out")

    def _h_wait(self, n):
        sec = float(n.properties.get("seconds", 1.0))
        time.sleep(sec)
        self._follow(n, "out")

    def _h_log(self, n):
        msg = n.properties.get("message", "")
        log.info(f"[流程日志] {self._template(msg)}")
        self._follow(n, "out")

    def _h_comment(self, _n):
        pass

    def _h_subflow(self, n):
        name = n.properties.get("flow_file", "")
        if name:
            p = FLOWS_DIR / name
            if p.exists():
                sub = FlowChart.load(str(p))
                ex = FlowExecutor(sub, self.engine, self._node_callback, self.step_delay)
                ex.variables = dict(self.variables)
                ex.execute()
                self.variables.update(ex.variables)
                log.debug(f"子流程完成: {name}")
            else:
                log.warning(f"子流程不存在: {p}")
        self._follow(n, "out")

    # ---------- 辅助 ----------
    def _template(self, t: str) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: str(self.variables.get(m.group(1), f"{{{m.group(1)}}}")), t)

    @staticmethod
    def _cast(raw: str) -> Any:
        if raw.lower() == "true": return True
        if raw.lower() == "false": return False
        try: return float(raw)
        except ValueError: return raw

    @staticmethod
    def _eval(actual, op, val_s) -> bool:
        try:
            a = float(actual) if actual is not None else 0.0
            b = float(val_s) if val_s else 0.0
            return {"==": a==b, "!=": a!=b, ">": a>b, "<": a<b, ">=": a>=b, "<=": a<=b}.get(op, False)
        except (ValueError, TypeError):
            a = str(actual) if actual is not None else ""
            return {"==": a==val_s, "!=": a!=val_s}.get(op, False)
