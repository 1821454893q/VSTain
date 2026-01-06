# tests/manual/demo_image_viewer.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QColor
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QFileDialog, QLabel

from vstain.components.image_viewer import ImageViewer, ViewerTool


class DemoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageViewer 手动测试 Demo")
        self.resize(1100, 720)

        self.viewer = ImageViewer()
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumWidth(420)
        self.status = QLabel("Ready")

        btn_load = QPushButton("加载图片…")
        btn_load.clicked.connect(self.load_image)

        btn_view = QPushButton("VIEW")
        btn_view.clicked.connect(lambda: self.set_tool(ViewerTool.VIEW))

        btn_pan = QPushButton("PAN")
        btn_pan.clicked.connect(lambda: self.set_tool(ViewerTool.PAN))

        btn_sel = QPushButton("SELECT")
        btn_sel.clicked.connect(lambda: self.set_tool(ViewerTool.SELECT))

        btn_reset = QPushButton("RESET")
        btn_reset.clicked.connect(self.viewer.reset_view)

        btn_clear = QPushButton("清除选区")
        btn_clear.clicked.connect(self.viewer.clear_selection)

        tools = QHBoxLayout()
        tools.addWidget(btn_load)
        tools.addSpacing(10)
        tools.addWidget(btn_view)
        tools.addWidget(btn_pan)
        tools.addWidget(btn_sel)
        tools.addSpacing(10)
        tools.addWidget(btn_reset)
        tools.addWidget(btn_clear)
        tools.addStretch(1)

        main = QHBoxLayout()
        main.addWidget(self.viewer, stretch=3)
        main.addWidget(self.out, stretch=2)

        root = QVBoxLayout(self)
        root.addLayout(tools)
        root.addLayout(main)
        root.addWidget(self.status)

        self.viewer.region_selected.connect(self.on_region)

        # default image
        pm = QPixmap(900, 520)
        pm.fill(QColor(245, 245, 245))
        self.viewer.set_image(pm)
        self.set_tool(ViewerTool.SELECT)
        self.log("Loaded default blank image 900x520")

    def log(self, msg: str):
        self.out.append(msg)
        print(msg)

    def set_tool(self, tool: ViewerTool):
        self.viewer.set_tool(tool)
        self.status.setText(f"Tool = {tool.value}")
        self.log(f"[TOOL] {tool.value}")

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            self.log(f"[ERROR] 加载失败: {path}")
            return
        self.viewer.set_image(pm)
        self.log(f"[LOAD] {path} size={pm.width()}x{pm.height()}")

    def on_region(self, r):
        self.log(f"==============================================")
        self.status.setText(f"Selected image rect: {r.image}")
        self.log(f"[REGION] display={r.display}")
        self.log(f"[REGION] normalized={r.normalized}")
        self.log(f"[REGION] image(px)={r.image}")
        self.log(f"==============================================")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    w = DemoWindow()
    w.show()
    sys.exit(app.exec_())


# uv run python -m tests.manual.demo_image_viewer
if __name__ == "__main__":
    main()
