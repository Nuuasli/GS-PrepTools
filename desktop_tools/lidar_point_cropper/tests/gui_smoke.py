"""Windows GUI smoke test. Run explicitly with pytest tests/gui_smoke.py -s."""

from hashlib import sha256
from pathlib import Path
from time import monotonic
from unittest.mock import patch

import numpy as np
from plyfile import PlyData
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from lidar_cropper.core import box_corners, load_selection_json
from lidar_cropper.gui import CropperWindow


def wait_until(predicate, timeout=15):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), 'Timed out waiting for the GUI'


def display_position(window, point):
    renderer = window.plotter.renderer
    renderer.SetWorldPoint(*point, 1)
    renderer.WorldToDisplay()
    x, y, _ = renderer.GetDisplayPoint()
    width, height = window.plotter.render_window.GetSize()
    viewport = window.plotter.interactor
    return QPoint(round(x * viewport.width() / width),
                  round((height - 1 - y) * viewport.height() / height))


def drag(viewport, button, start, offset):
    QTest.mouseMove(viewport, start)
    QTest.mousePress(viewport, button, pos=start)
    for step in range(1, 6):
        point = start + QPoint(offset.x() * step // 5, offset.y() * step // 5)
        QTest.mouseMove(viewport, point, delay=20)
    QTest.mouseRelease(viewport, button, pos=start + offset)
    QTest.qWait(50)


def test_windows_demo_gui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows', 'Smoke test requires the Windows Qt viewport'
    source = Path(__file__).resolve().parents[1] / 'demo_scan.ply'
    source_hash = sha256(source.read_bytes()).hexdigest()
    window = CropperWindow()
    window.showMaximized()
    click = Qt.MouseButton.LeftButton
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[2]))
    try:
        assert QTest.qWaitForWindowExposed(window)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
            QTest.mouseClick(window.open_btn, click)
            wait_until(lambda: window.task is None and window.doc is not None)

        assert window.doc.count == 78_000
        assert window.plotter.renderer.actors['original'].mapper.dataset.n_points == 78_000
        top = next(b for b in window.findChildren(QPushButton) if b.text() == 'Top')
        viewport = window.plotter.interactor
        initial_image = window.plotter.screenshot()
        assert np.count_nonzero((initial_image[..., 0] > 150) & (initial_image[..., 1] > 65)) > 100

        # Press and drag a VTK handle in AABB mode, then preview the smaller area.
        window.mode_combo.setCurrentIndex(1)
        QTest.mouseClick(top, click)
        before = box_corners(window.roi)
        center = before.mean(axis=0)
        face = [before[:, 0].min(), center[1], center[2]]
        start = display_position(window, face)
        drag(viewport, click, start, QPoint(65, 0))
        after = box_corners(window.roi)
        assert after[:, 0].min() > before[:, 0].min()
        np.testing.assert_allclose(np.max(np.abs(window.roi.normals), axis=1), 1.)
        QTest.mouseClick(window.preview_btn, click)
        assert window.export_btn.isEnabled()
        aabb_count = window.plotter.renderer.actors['selected'].mapper.dataset.n_points
        assert 0 < aabb_count < window.doc.count
        face[0] = after[:, 0].min()
        drag(viewport, click, display_position(window, face), QPoint(25, 0))
        assert not window.export_btn.isEnabled()
        assert 'selected' not in window.plotter.renderer.actors

        # Drag the face of the box in OBB mode to rotate it using the VTK widget.
        window.mode_combo.setCurrentIndex(0)
        QTest.mouseClick(top, click)
        before = box_corners(window.roi)
        center = before.mean(axis=0)
        start = display_position(window, [center[0] + 0.8, center[1] + 0.8, before[:, 2].max()])
        drag(viewport, click, start, QPoint(70, 45))
        assert np.any(np.max(np.abs(window.roi.normals), axis=1) < .999)
        assert not window.export_btn.isEnabled()
        QTest.mouseClick(window.preview_btn, click)
        assert window.export_btn.isEnabled()
        window.show_original.setChecked(False)
        rendered = window.plotter.screenshot(tmp_path / 'obb_preview.png')
        assert np.count_nonzero((rendered[..., 0] > 150) & (rendered[..., 1] > 65)) > 100
        selected = window.plotter.renderer.actors['selected'].mapper.dataset.n_points
        assert 0 < selected < window.doc.count

        destination = tmp_path / 'demo_crop.ply'
        with (
            patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), '')),
            patch.object(QMessageBox, 'information') as confirmed,
        ):
            QTest.mouseClick(window.export_btn, click)
            wait_until(lambda: window.task is None and destination.exists())
            confirmed.assert_called_once()

        metadata = destination.with_name('demo_crop_selection.json')
        roi = load_selection_json(metadata, window.doc)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(metadata), '')):
            QTest.mouseClick(window.load_roi_btn, click)
        assert window.roi_locked
        QTest.mouseClick(window.preview_btn, click)
        replayed = window.plotter.renderer.actors['selected'].mapper.dataset.n_points
        assert replayed == selected

        mask = roi.mask(window.coords)
        actual = PlyData.read(str(destination))['vertex'].data
        expected = window.doc.vertices[mask]
        assert len(actual) == selected
        assert actual.dtype == expected.dtype
        assert actual.tobytes() == expected.tobytes()
        assert sha256(source.read_bytes()).hexdigest() == source_hash

        assert not errors
        broken = tmp_path / 'invalid.ply'
        broken.write_text('invalid header', encoding='ascii')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(broken), '')):
            QTest.mouseClick(window.open_btn, click)
            wait_until(lambda: window.task is None and errors)
        assert window.doc.path == source
        assert window.export_btn.isEnabled()
        print(f'Windows OpenGL, AABB preview {aabb_count:,}, OBB preview/export '
              f'{selected:,}/{window.doc.count:,}, JSON replay {replayed:,}.\n'
              f'Viewport capture: {tmp_path / "obb_preview.png"}')
    finally:
        wait_until(lambda: window.task is None)
        window.close()
        app.processEvents()
        assert not window.isVisible()
