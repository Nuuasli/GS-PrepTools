"""Qt overlay and VTK camera capture for viewport polygon drawing."""
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .polygon import CameraProjection, MAX_VERTICES, screen_to_uv, uv_to_screen


def _matrix(vtk_matrix):
    return np.array([[vtk_matrix.GetElement(row, col) for col in range(4)] for row in range(4)])


def capture_projection(plotter):
    renderer = plotter.renderer
    camera = renderer.GetActiveCamera()
    return CameraProjection(
        _matrix(camera.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1, 1)),
        _matrix(camera.GetModelViewTransformMatrix()),
        camera.GetClippingRange(),
        'orthographic' if camera.GetParallelProjection() else 'perspective',
        renderer.GetViewport(),
        plotter.render_window.GetSize(),
        plotter.interactor.devicePixelRatioF(),
    )


class ViewportOverlay(QWidget):
    interrupted = Signal()

    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.camera = None
        self.setStyleSheet('background: transparent;')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        viewport.installEventFilter(self)
        self.hide()

    def begin(self, camera):
        self.camera = camera
        self.setGeometry(self.viewport.rect())
        self.show()
        self.raise_()
        self.setFocus()

    def finish(self):
        self.camera = None
        self.hide()
        self.viewport.setFocus()

    def eventFilter(self, watched, event):
        if watched is self.viewport and self.camera is not None:
            resized = event.type() == QEvent.Type.Resize and event.size() != self.size()
            dpi_changed = (event.type() == QEvent.Type.DevicePixelRatioChange
                           and self.viewport.devicePixelRatioF() != self.camera.device_pixel_ratio)
            if resized or dpi_changed:
                self.interrupted.emit()
            elif event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                                  QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseMove,
                                  QEvent.Type.Wheel, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
                                  QEvent.Type.NativeGesture, QEvent.Type.Gesture):
                return True
        return False

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()


class PolygonOverlay(ViewportOverlay):
    vertices_changed = Signal(int)

    def __init__(self, viewport):
        super().__init__(viewport)
        self.vertices = []

    def begin(self, camera):
        self.vertices.clear()
        super().begin(camera)
        self.vertices_changed.emit(0)

    def finish(self):
        self.vertices.clear()
        super().finish()

    def mousePressEvent(self, event):
        if self.camera is not None and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            uv = screen_to_uv(pos.x(), pos.y(), self.width(), self.height(), self.camera.viewport)
            if len(self.vertices) < MAX_VERTICES and all(0 <= value <= 1 for value in uv):
                self.vertices.append(uv)
                self.vertices_changed.emit(len(self.vertices))
                self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Backspace and self.vertices:
            self.vertices.pop()
            self.vertices_changed.emit(len(self.vertices))
            self.update()
        event.accept()

    def paintEvent(self, event):
        if self.camera is None or not self.vertices:
            return
        points = QPolygonF([QPointF(*uv_to_screen(
            *vertex, self.width(), self.height(), self.camera.viewport)) for vertex in self.vertices])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#ffd3a0'), 2))
        painter.drawPolyline(points)
        painter.setBrush(QColor('#ffd3a0'))
        for point in points:
            painter.drawEllipse(point, 3.5, 3.5)
