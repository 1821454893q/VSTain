import time
import json
from dataclasses import dataclass, field
from typing import Optional, Literal
from pathlib import Path

from src.vstain.utils.logger import get_logger

log = get_logger()


@dataclass
class OperationData:
    """优化后的操作数据类"""

    # 核心标识字段
    type: Literal["mouse", "keyboard"]
    timestamp: float = field(default_factory=time.time)

    # 鼠标操作字段
    mouse_action: Optional[Literal["click", "move", "scroll"]] = None
    mouse_button: Optional[Literal["left", "right", "middle"]] = None
    mouse_event: Optional[Literal["down", "up"]] = None
    pos_x: Optional[float] = None  # 归一化坐标 [0, 1]
    pos_y: Optional[float] = None
    scroll: Optional[int] = None

    # 键盘操作字段
    key: Optional[str] = None
    key_event: Optional[Literal["down", "up"]] = None

    def __post_init__(self):
        """数据验证"""
        if self.type == "mouse":
            assert self.mouse_action is not None, "鼠标操作必须指定动作类型"
            if self.mouse_action == "click":
                assert self.mouse_button is not None, "点击操作必须指定按钮"
                assert self.mouse_event is not None, "点击操作必须指定事件"
            if self.mouse_action in ["click", "move"]:
                assert self.pos_x is not None and self.pos_y is not None, "点击和移动操作必须指定坐标"

        elif self.type == "keyboard":
            assert self.key is not None, "键盘操作必须指定按键"
            assert self.key_event is not None, "键盘操作必须指定事件"


class OperationRecorder:
    """
    优化后的操作录制器
    """

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080):
        self.operations: list[OperationData] = []
        self.is_recording = False
        self.start_time = None
        self.screen_width = screen_width
        self.screen_height = screen_height

    def start_recording(self, screen_width: int = None, screen_height: int = None):
        """
        开始录制操作

        Args:
            screen_width: 屏幕宽度，用于坐标归一化
            screen_height: 屏幕高度，用于坐标归一化
        """
        self.operations.clear()
        self.is_recording = True
        self.start_time = time.time()

        if screen_width is not None:
            self.screen_width = screen_width
        if screen_height is not None:
            self.screen_height = screen_height

        log.info(f"开始录制操作 - 屏幕尺寸: {self.screen_width}x{self.screen_height}")

    def stop_recording(self):
        """停止录制操作"""
        self.is_recording = False
        operation_count = len(self.operations)
        log.info(f"停止录制，共录制 {operation_count} 个操作")

    def update_screen_size(self, width: int, height: int):
        """更新屏幕尺寸"""
        self.screen_width = width
        self.screen_height = height
        log.debug(f"更新屏幕尺寸: {width}x{height}")

    # ==================== 鼠标操作录制 ====================

    def add_mouse_click(self, x: int, y: int, button: str = "left", event: str = "down"):
        """
        添加鼠标点击操作

        Args:
            x: 屏幕坐标x
            y: 屏幕坐标y
            button: 鼠标按钮 left/right/middle
            event: 事件类型 down/up
        """
        if not self.is_recording:
            return

        operation = OperationData(
            type="mouse",
            mouse_action="click",
            mouse_button=button,
            mouse_event=event,
            pos_x=self._normalize_x(x),
            pos_y=self._normalize_y(y),
            timestamp=time.time() - self.start_time,
        )
        self.operations.append(operation)
        log.debug(f"录制鼠标点击: {button} {event} at ({x}, {y})")

    def add_mouse_move(self, x: int, y: int):
        """
        添加鼠标移动操作
        """
        if not self.is_recording:
            return

        operation = OperationData(
            type="mouse",
            mouse_action="move",
            pos_x=self._normalize_x(x),
            pos_y=self._normalize_y(y),
            timestamp=time.time() - self.start_time,
        )
        self.operations.append(operation)
        log.debug(f"录制鼠标移动: ({x}, {y})")

    def add_mouse_scroll(self, x: int, y: int, delta: int):
        """
        添加鼠标滚轮操作
        """
        if not self.is_recording:
            return

        operation = OperationData(
            type="mouse",
            mouse_action="scroll",
            pos_x=self._normalize_x(x),
            pos_y=self._normalize_y(y),
            scroll=delta,
            timestamp=time.time() - self.start_time,
        )
        self.operations.append(operation)
        log.debug(f"录制鼠标滚轮: delta={delta} at ({x}, {y})")

    # ==================== 键盘操作录制 ====================

    def add_keyboard(self, key: str, event: str = "down"):
        """
        添加键盘事件

        Args:
            key: 按键名称
            event: 事件类型 down/up
        """
        if not self.is_recording:
            return

        operation = OperationData(type="keyboard", key=key, key_event=event, timestamp=time.time() - self.start_time)
        self.operations.append(operation)
        log.debug(f"录制键盘事件: {key} {event}")

    # ==================== 工具方法 ====================

    def _normalize_x(self, x: int) -> float:
        """将x坐标归一化到0-1范围"""
        return x / self.screen_width if self.screen_width > 0 else 0

    def _normalize_y(self, y: int) -> float:
        """将y坐标归一化到0-1范围"""
        return y / self.screen_height if self.screen_height > 0 else 0

    def _denormalize_x(self, x: float) -> int:
        """将归一化x坐标还原为实际坐标"""
        return int(x * self.screen_width)

    def _denormalize_y(self, y: float) -> int:
        """将归一化y坐标还原为实际坐标"""
        return int(y * self.screen_height)

    def get_operations(self) -> list[OperationData]:
        """获取录制的操作列表"""
        return self.operations.copy()

    def clear_operations(self):
        """清空操作记录"""
        self.operations.clear()
        log.info("清空操作记录")

    def save_to_file(self, filename: str):
        """保存操作记录到JSON文件"""
        try:
            data = {
                "screen_width": self.screen_width,
                "screen_height": self.screen_height,
                "start_time": self.start_time,
                "operations": [
                    {
                        "type": op.type,
                        "timestamp": op.timestamp,
                        "mouse_action": op.mouse_action,
                        "mouse_button": op.mouse_button,
                        "mouse_event": op.mouse_event,
                        "pos_x": op.pos_x,
                        "pos_y": op.pos_y,
                        "scroll": op.scroll,
                        "key": op.key,
                        "key_event": op.key_event,
                    }
                    for op in self.operations
                ],
            }

            # 确保目录存在
            Path(filename).parent.mkdir(parents=True, exist_ok=True)

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            log.info(f"操作记录已保存到: {filename}")
            return True

        except Exception as e:
            log.error(f"保存操作记录失败: {e}")
            return False

    def load_from_file(self, filename: str):
        """从JSON文件加载操作记录"""
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.screen_width = data.get("screen_width", 1920)
            self.screen_height = data.get("screen_height", 1080)
            self.start_time = data.get("start_time")

            self.operations = []
            for op_data in data.get("operations", []):
                operation = OperationData(
                    type=op_data["type"],
                    timestamp=op_data["timestamp"],
                    mouse_action=op_data.get("mouse_action"),
                    mouse_button=op_data.get("mouse_button"),
                    mouse_event=op_data.get("mouse_event"),
                    pos_x=op_data.get("pos_x"),
                    pos_y=op_data.get("pos_y"),
                    scroll=op_data.get("scroll"),
                    key=op_data.get("key"),
                    key_event=op_data.get("key_event"),
                )
                self.operations.append(operation)

            log.info(f"操作记录已从 {filename} 加载，共 {len(self.operations)} 个操作")
            return True

        except Exception as e:
            log.error(f"加载操作记录失败: {e}")
            return False

    @property
    def operation_count(self) -> int:
        """获取操作数量"""
        return len(self.operations)

    @property
    def recording_duration(self) -> float:
        """获取录制时长（秒）"""
        if self.start_time and self.is_recording:
            return time.time() - self.start_time
        return 0.0
