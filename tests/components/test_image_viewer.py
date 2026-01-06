import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QPixmap, QColor
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

from vstain.components.image_viewer import ImageViewer, ViewerTool


class TestImageViewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def _make_viewer(self):
        v = ImageViewer()
        v.resize(500, 500)
        pm = QPixmap(200, 100)
        pm.fill(QColor(255, 255, 255))
        self.assertTrue(v.set_image(pm))
        v.set_tool(ViewerTool.SELECT)

        v.show()
        v.raise_()
        v.activateWindow()
        v.setFocus(Qt.OtherFocusReason)
        QTest.qWaitForWindowExposed(v)
        QTest.qWait(50)
        return v

    def test_zoom_in_out(self):
        v = self._make_viewer()
        z0 = v.zoom()
        v.zoom_in()
        self.assertGreater(v.zoom(), z0)
        v.zoom_out()
        self.assertAlmostEqual(v.zoom(), z0, delta=0.3)

    def test_select_region_emits(self):
        v = self._make_viewer()
        captured = {"r": None}
        v.region_selected.connect(lambda r: captured.__setitem__("r", r))

        p1 = QPoint(120, 140)
        p2 = QPoint(280, 260)

        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, p1, delay=10)
        # mouseMove 不一定可靠，但这里有也无妨
        QTest.mouseMove(v, p2, delay=10)
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, p2, delay=10)
        QTest.qWait(50)

        self.assertIsNotNone(captured["r"])
        r = captured["r"]

        # image rect must be within 200x100
        self.assertGreaterEqual(r.image.x(), 0)
        self.assertGreaterEqual(r.image.y(), 0)
        self.assertLessEqual(r.image.x() + r.image.width(), 200)
        self.assertLessEqual(r.image.y() + r.image.height(), 100)

        # normalized must be within 0..1
        self.assertGreaterEqual(r.normalized.left(), 0.0)
        self.assertGreaterEqual(r.normalized.top(), 0.0)
        self.assertLessEqual(r.normalized.right(), 1.0)
        self.assertLessEqual(r.normalized.bottom(), 1.0)


# uv run python -m unittest tests.components.test_image_viewer
if __name__ == "__main__":
    unittest.main()
