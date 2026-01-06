# src/vstain/components/image_viewer.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from PyQt5.QtCore import Qt, QPointF, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QWheelEvent, QMouseEvent
from PyQt5.QtWidgets import QWidget


class ViewerTool(str, Enum):
    VIEW = "view"
    PAN = "pan"
    SELECT = "select"


@dataclass(frozen=True)
class Region:
    """A selected region expressed in 3 coordinate spaces."""

    display: QRectF  # widget/display coords
    normalized: QRectF  # 0..1 in image space
    image: QRect  # int pixel coords in original image


class ImageViewer(QWidget):
    """
    A simple, reusable image viewer widget.

    - set_image(QPixmap)
    - set_tool(VIEW/PAN/SELECT)
    - wheel zoom (cursor-centered)
    - drag pan (PAN tool)
    - drag selection (SELECT tool)
    - emits Region with display/normalized/image coords
    """

    region_selected = pyqtSignal(Region)
    tool_changed = pyqtSignal(object)  # ViewerTool
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._pixmap: Optional[QPixmap] = None

        self._tool: ViewerTool = ViewerTool.VIEW

        # View transform (widget coords)
        self._zoom: float = 1.0
        self._min_zoom: float = 0.05
        self._max_zoom: float = 40.0
        self._wheel_ratio: float = 1.1

        self._pan: QPointF = QPointF(0.0, 0.0)  # widget pixels

        # Interaction state
        self._panning: bool = False
        self._pan_last: Optional[QPointF] = None

        self._selecting: bool = False
        self._sel_start: Optional[QPointF] = None
        self._sel_end: Optional[QPointF] = None
        self._selection: Optional[Region] = None

        # Visuals
        self._bg = QColor(30, 30, 30)
        self._sel_fill = QColor(0, 120, 215, 60)
        self._sel_border = QColor(0, 120, 215, 200)

    # -------------------------
    # Public API
    # -------------------------
    def set_image(self, pixmap: QPixmap) -> bool:
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
            self._selection = None
            self.update()
            return False

        self._pixmap = pixmap
        self.reset_view()
        self.update()
        return True

    def image(self) -> Optional[QPixmap]:
        return self._pixmap

    def set_tool(self, tool: ViewerTool) -> None:
        if isinstance(tool, str):
            tool = ViewerTool(tool)

        if self._tool != tool:
            self._tool = tool
            self._panning = False
            self._selecting = False
            self._pan_last = None
            self._sel_start = None
            self._sel_end = None
            self._update_cursor()
            self.tool_changed.emit(self._tool)
            self.update()

    def tool(self) -> ViewerTool:
        return self._tool

    def zoom(self) -> float:
        return self._zoom

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._panning = False
        self._selecting = False
        self._pan_last = None
        self._sel_start = None
        self._sel_end = None
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_in(self) -> None:
        self._apply_zoom(self._zoom * self._wheel_ratio, anchor=None)

    def zoom_out(self) -> None:
        self._apply_zoom(self._zoom / self._wheel_ratio, anchor=None)

    def clear_selection(self) -> None:
        self._selection = None
        self._selecting = False
        self._sel_start = None
        self._sel_end = None
        self.update()

    def selection(self) -> Optional[Region]:
        return self._selection

    # -------------------------
    # Coordinate transforms
    # -------------------------
    def _content_rect(self) -> QRectF:
        # Full drawable area (no margins)
        r = self.rect()
        return QRectF(0.0, 0.0, float(r.width()), float(r.height()))

    def _fit_rect(self) -> Optional[QRectF]:
        """Image rect in widget coords at zoom=1, pan=0 (aspect fit)."""
        if not self._pixmap or self._pixmap.isNull():
            return None

        cw = max(1.0, self._content_rect().width())
        ch = max(1.0, self._content_rect().height())
        iw = float(self._pixmap.width())
        ih = float(self._pixmap.height())

        scale = min(cw / iw, ch / ih)
        w = iw * scale
        h = ih * scale
        x = (cw - w) / 2.0
        y = (ch - h) / 2.0
        return QRectF(x, y, w, h)

    def _scale(self) -> float:
        """Effective scale from image pixels -> widget pixels."""
        fr = self._fit_rect()
        if not fr:
            return 1.0
        return (fr.width() / float(self._pixmap.width())) * self._zoom

    def display_to_image(self, p: QPointF) -> Optional[QPointF]:
        """Widget/display coords -> image pixel coords (float)."""
        fr = self._fit_rect()
        if not fr or not self._pixmap:
            return None
        s = self._scale()
        if s <= 1e-9:
            return None

        x = (p.x() - (fr.x() + self._pan.x())) / s
        y = (p.y() - (fr.y() + self._pan.y())) / s
        return QPointF(x, y)

    def image_to_display(self, p: QPointF) -> Optional[QPointF]:
        """Image pixel coords (float) -> widget/display coords."""
        fr = self._fit_rect()
        if not fr or not self._pixmap:
            return None
        s = self._scale()
        x = fr.x() + self._pan.x() + p.x() * s
        y = fr.y() + self._pan.y() + p.y() * s
        return QPointF(x, y)

    def image_to_normalized(self, p: QPointF) -> Optional[QPointF]:
        if not self._pixmap:
            return None
        iw = float(self._pixmap.width())
        ih = float(self._pixmap.height())
        if iw <= 0 or ih <= 0:
            return None
        return QPointF(p.x() / iw, p.y() / ih)

    def normalized_to_image(self, p: QPointF) -> Optional[QPointF]:
        if not self._pixmap:
            return None
        return QPointF(p.x() * self._pixmap.width(), p.y() * self._pixmap.height())

    def _clamp_image_point(self, p: QPointF) -> QPointF:
        if not self._pixmap:
            return p
        x = min(max(p.x(), 0.0), float(self._pixmap.width()))
        y = min(max(p.y(), 0.0), float(self._pixmap.height()))
        return QPointF(x, y)

    def _build_region_from_display_rect(self, dr: QRectF) -> Optional[Region]:
        if not self._pixmap:
            return None

        # Convert display rect corners -> image float coords
        p1 = self.display_to_image(QPointF(dr.left(), dr.top()))
        p2 = self.display_to_image(QPointF(dr.right(), dr.bottom()))
        if p1 is None or p2 is None:
            return None

        p1 = self._clamp_image_point(p1)
        p2 = self._clamp_image_point(p2)

        x1, y1 = min(p1.x(), p2.x()), min(p1.y(), p2.y())
        x2, y2 = max(p1.x(), p2.x()), max(p1.y(), p2.y())

        # Avoid empty regions
        if (x2 - x1) < 1.0 or (y2 - y1) < 1.0:
            return None

        img_rect = QRect(int(x1), int(y1), max(1, int(x2 - x1)), max(1, int(y2 - y1)))

        # normalized rect
        n1 = self.image_to_normalized(QPointF(x1, y1))
        n2 = self.image_to_normalized(QPointF(x2, y2))
        if n1 is None or n2 is None:
            return None

        nx1, ny1 = max(0.0, min(n1.x(), n2.x())), max(0.0, min(n1.y(), n2.y()))
        nx2, ny2 = min(1.0, max(n1.x(), n2.x())), min(1.0, max(n1.y(), n2.y()))
        norm_rect = QRectF(nx1, ny1, max(0.0, nx2 - nx1), max(0.0, ny2 - ny1))

        return Region(display=dr, normalized=norm_rect, image=img_rect)

    # -------------------------
    # Events
    # -------------------------
    def _update_cursor(self) -> None:
        if self._tool == ViewerTool.PAN:
            self.setCursor(Qt.OpenHandCursor)
        elif self._tool == ViewerTool.SELECT:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        if not self._pixmap:
            return super().mousePressEvent(event)

        pos = QPointF(event.pos())

        if self._tool == ViewerTool.PAN:
            self._panning = True
            self._pan_last = pos
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if self._tool == ViewerTool.SELECT:
            self._selecting = True
            self._sel_start = pos
            self._sel_end = pos
            event.accept()
            self.update()
            return

        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = QPointF(event.pos())

        if self._panning and self._tool == ViewerTool.PAN and self._pan_last is not None:
            delta = pos - self._pan_last
            self._pan += delta
            self._pan_last = pos
            event.accept()
            self.update()
            return

        if self._selecting and self._tool == ViewerTool.SELECT:
            self._sel_end = pos
            event.accept()
            self.update()
            return

        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)

        pos = QPointF(event.pos())

        if self._panning and self._tool == ViewerTool.PAN:
            self._panning = False
            self._pan_last = None
            self._update_cursor()
            event.accept()
            return

        if self._selecting and self._tool == ViewerTool.SELECT:
            # Important: do NOT rely on mouseMove being delivered (unit tests / some platforms)
            self._sel_end = pos

            if self._sel_start is not None and self._sel_end is not None:
                x1 = min(self._sel_start.x(), self._sel_end.x())
                y1 = min(self._sel_start.y(), self._sel_end.y())
                x2 = max(self._sel_start.x(), self._sel_end.x())
                y2 = max(self._sel_start.y(), self._sel_end.y())
                dr = QRectF(x1, y1, x2 - x1, y2 - y1)

                # Small threshold in display pixels
                if dr.width() >= 3.0 and dr.height() >= 3.0:
                    region = self._build_region_from_display_rect(dr)
                    if region:
                        self._selection = region
                        self.region_selected.emit(region)

            self._selecting = False
            self._sel_start = None
            self._sel_end = None
            event.accept()
            self.update()
            return

        return super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._pixmap:
            return super().wheelEvent(event)

        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)

        anchor = QPointF(event.pos())
        if delta > 0:
            new_zoom = self._zoom * self._wheel_ratio
        else:
            new_zoom = self._zoom / self._wheel_ratio

        self._apply_zoom(new_zoom, anchor=anchor)
        event.accept()

    def _apply_zoom(self, new_zoom: float, anchor: Optional[QPointF]) -> None:
        new_zoom = max(self._min_zoom, min(self._max_zoom, float(new_zoom)))
        if abs(new_zoom - self._zoom) < 1e-9:
            return

        fr = self._fit_rect()
        if not fr or not self._pixmap:
            self._zoom = new_zoom
            self.zoom_changed.emit(self._zoom)
            self.update()
            return

        if anchor is None:
            # zoom around center
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)

        # Keep the image point under cursor stable:
        img_before = self.display_to_image(anchor)
        if img_before is None:
            self._zoom = new_zoom
            self.zoom_changed.emit(self._zoom)
            self.update()
            return

        self._zoom = new_zoom
        s = self._scale()

        # Solve pan: anchor = fr.topLeft + pan + img * scale
        self._pan = QPointF(
            anchor.x() - fr.x() - img_before.x() * s,
            anchor.y() - fr.y() - img_before.y() * s,
        )

        self.zoom_changed.emit(self._zoom)
        self.update()

    # -------------------------
    # Painting
    # -------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # background
        painter.fillRect(self.rect(), self._bg)

        if not self._pixmap or self._pixmap.isNull():
            painter.end()
            return

        fr = self._fit_rect()
        if not fr:
            painter.end()
            return

        s = self._scale()

        # Draw image with transform (simple formula, no QTransform needed)
        target = QRectF(
            fr.x() + self._pan.x(),
            fr.y() + self._pan.y(),
            self._pixmap.width() * s,
            self._pixmap.height() * s,
        )
        painter.drawPixmap(target, self._pixmap, QRectF(0, 0, self._pixmap.width(), self._pixmap.height()))

        # Selection overlay (during drag)
        if self._tool == ViewerTool.SELECT and self._selecting and self._sel_start and self._sel_end:
            x1 = min(self._sel_start.x(), self._sel_end.x())
            y1 = min(self._sel_start.y(), self._sel_end.y())
            x2 = max(self._sel_start.x(), self._sel_end.x())
            y2 = max(self._sel_start.y(), self._sel_end.y())
            dr = QRectF(x1, y1, x2 - x1, y2 - y1)

            painter.setBrush(QBrush(self._sel_fill))
            painter.setPen(QPen(self._sel_border, 2))
            painter.drawRect(dr)

        # Selection overlay (final selection)
        if self._selection is not None and not self._selecting:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(self._sel_border, 2))
            painter.drawRect(self._selection.display)

        painter.end()
