"""Mouse stroke capture and lightweight viewport feedback."""
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from .brush import MAX_STROKE_POINTS
from .polygon import screen_to_uv, uv_to_screen
from .polygon_ui import ViewportOverlay


class BrushOverlay(ViewportOverlay):
    stroke_started = Signal()
    stroke_ready = Signal()
    stroke_too_long = Signal()

    def __init__(self, viewport):
        super().__init__(viewport)
        self.setMouseTracking(True)
        self.points = []
        self.pointer = None
        self.drawing = False
        self.finished = False
        self.radius = 24
        self.restore = False

    def finish(self):
        self.points.clear()
        self.pointer = None
        self.drawing = self.finished = False
        super().finish()

    def _sample(self, pos, *, final=False):
        uv = screen_to_uv(pos.x(), pos.y(), self.width(), self.height(), self.camera.viewport)
        uv = tuple(min(1., max(0., coord)) for coord in uv)
        if self.points:
            last = uv_to_screen(*self.points[-1], self.width(), self.height(), self.camera.viewport)
            if uv == self.points[-1] or (not final and (pos.x()-last[0])**2 + (pos.y()-last[1])**2 < 4):
                return
        if len(self.points) >= MAX_STROKE_POINTS:
            self.stroke_too_long.emit()
            return
        self.points.append(uv)

    def mousePressEvent(self, event):
        if self.camera is not None and not self.finished and event.button() == Qt.MouseButton.LeftButton:
            self.pointer = event.position()
            self.drawing = True
            self._sample(self.pointer)
            self.stroke_started.emit()
            self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        self.pointer = event.position()
        if self.drawing:
            self._sample(self.pointer)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            self.pointer = event.position()
            self._sample(self.pointer, final=True)
            if self.camera is not None:
                self.drawing = False
                self.finished = True
                self.stroke_ready.emit()
                self.update()
        event.accept()

    def leaveEvent(self, event):
        self.pointer = None
        self.update()

    def paintEvent(self, event):
        if self.camera is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor('#58d9a6' if self.restore else '#ff856e')
        fill.setAlpha(95)
        if self.points:
            pixels = [QPointF(*uv_to_screen(*p, self.width(), self.height(), self.camera.viewport))
                      for p in self.points]
            if len(pixels) == 1:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawEllipse(pixels[0], self.radius, self.radius)
            else:
                path = QPainterPath(pixels[0])
                for pixel in pixels[1:]:
                    path.lineTo(pixel)
                painter.setPen(QPen(fill, self.radius * 2, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(path)
        if self.pointer is not None and not self.finished:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#ffffff'), 1.5))
            painter.drawEllipse(self.pointer, self.radius, self.radius)
