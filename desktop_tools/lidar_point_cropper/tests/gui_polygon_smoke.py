"""Windows Qt events and a read-only preview of one optional research LAS."""
import os
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import laspy
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from lidar_cropper.core import file_sha256
from lidar_cropper.gui import CropperWindow
from tests.gui_las_smoke import build_fixture, peak_rss_mib
from tests.gui_smoke import drag, wait_until


LEFT = Qt.MouseButton.LeftButton
RIGHT = Qt.MouseButton.RightButton


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows'
    view = CropperWindow()
    view.showMaximized()
    assert QTest.qWaitForWindowExposed(view)
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[2]))
    try:
        yield view
        assert not errors, errors
    finally:
        wait_until(lambda: view.task is None, timeout=120)
        view.close()
        app.processEvents()


def open_cloud(window, source):
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
        QTest.mouseClick(window.open_btn, LEFT)
        wait_until(lambda: window.task is None, timeout=120)
    assert window.doc is not None
    QTest.qWait(150)  # Let Qt lay out the newly populated metadata and preview panels.


def begin(window, kind='keep'):
    QTest.mouseClick(window.draw_polygon_btn, LEFT)
    assert window.polygon_overlay.camera is not None
    window.polygon_operation.setCurrentIndex(0 if kind == 'keep' else 1)
    return window.polygon_overlay


def vertex(overlay, u, v):
    QTest.mouseClick(overlay, LEFT, pos=QPoint(round(u * overlay.width()), round(v * overlay.height())))


def rectangle(overlay, left, top, right, bottom):
    for point in ((left, top), (right, top), (right, bottom), (left, bottom)):
        vertex(overlay, *point)


def test_polygon_mouse_and_replay(window, tmp_path):
    source = build_fixture(tmp_path / 'synthetic.laz')
    before_source = file_sha256(source)
    open_cloud(window, source)
    window.plotter.camera_position = [(0, 0, 10), (0, 0, 0), (0, 1, 0)]
    window.plotter.reset_camera_clipping_range()
    window.plotter.render()

    original_roi = window.roi
    overlay = begin(window)
    pose_frozen = window.plotter.camera.GetPosition()
    vertex(overlay, .4, .4)
    vertex(overlay, .5, .5)
    assert len(overlay.vertices) == 2 and not window.confirm_polygon_btn.isEnabled()
    QTest.keyClick(overlay, Qt.Key.Key_Backspace)
    assert len(overlay.vertices) == 1
    drag(overlay, RIGHT, QPoint(200, 120), QPoint(50, 30))
    assert overlay.camera is not None, window.statusBar().currentMessage()
    assert window.plotter.camera.GetPosition() == pose_frozen
    top = next(btn for btn in window.findChildren(QPushButton) if btn.text() == 'Top')
    QTest.mouseClick(top, LEFT)
    assert window.plotter.camera.GetPosition() == pose_frozen
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    wait_until(lambda: overlay.camera is None)
    assert not overlay.isVisible() and window.roi is original_roi

    overlay = begin(window)
    for uv in ((.3, .5), (.5, .5), (.7, .5)):
        vertex(overlay, *uv)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    assert overlay.camera is not None and window.roi is original_roi
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    wait_until(lambda: overlay.camera is None)

    overlay = begin(window)
    rectangle(overlay, .3, .25, .58, .75)
    draft_capture = tmp_path / 'polygon_draft.png'
    assert overlay.grab().save(str(draft_capture))
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    assert overlay.camera is None
    assert window.roi.initial_box is original_roi
    first_mask = window.roi.mask(window.coords)
    assert 0 < first_mask.sum() < window.doc.count
    assert window.roi.operations[0].camera.mode == 'perspective'

    # View change and a second projection narrow the existing selection.
    QTest.mouseClick(top, LEFT)
    assert window.plotter.camera.GetPosition() != pose_frozen
    window.projection_combo.setCurrentIndex(1)
    np.testing.assert_array_equal(window.roi.mask(window.coords), first_mask)
    overlay = begin(window, 'remove')
    rectangle(overlay, .35, .4, .65, .59)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    assert overlay.camera is None and len(window.roi.operations) == 2
    assert window.roi.operations[1].camera.mode == 'orthographic'
    selected = window.roi.mask(window.coords)
    assert 0 < selected.sum() < first_mask.sum()
    assert not np.any(selected & ~first_mask)
    assert window.plotter.renderer.actors['selected'].mapper.dataset.n_points == selected.sum()

    output = tmp_path / 'polygon_crop.las'
    with (
        patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), '')),
        patch.object(QMessageBox, 'information') as completed,
    ):
        QTest.mouseClick(window.export_btn, LEFT)
        wait_until(lambda: window.task is None, timeout=120)
        completed.assert_called_once()
    actual = laspy.read(output).points.array
    original = laspy.read(source).points.array
    assert actual.tobytes() == original[selected].tobytes()
    assert file_sha256(source) == before_source

    # Resizing mid-draft cancels only the draft. Replay uses the saved view matrices.
    size_before = window.plotter.interactor.size()
    overlay = begin(window)
    vertex(overlay, .5, .5)
    window.showNormal()
    window.resize(1240, 760)
    wait_until(lambda: window.plotter.interactor.size() != size_before and overlay.camera is None)
    np.testing.assert_array_equal(window.roi.mask(window.coords), selected)
    metadata = output.with_name('polygon_crop_selection.json')
    QTest.mouseClick(window.reset_btn, LEFT)
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(metadata), '')):
        QTest.mouseClick(window.load_roi_btn, LEFT)
    np.testing.assert_array_equal(window.roi.mask(window.coords), selected)
    assert window.plotter.renderer.actors['selected'].mapper.dataset.n_points == selected.sum()
    assert window.mode_combo.isEnabled() is False
    print(f'GUI synthetic: {first_mask.sum():,} kept, {selected.sum():,} after remove, '
          f'DPR {window.plotter.interactor.devicePixelRatioF()}, peak {peak_rss_mib():.1f} MiB. {tmp_path}')


@pytest.mark.skipif(not os.environ.get('LIDAR_POLYGON_SMOKE_SOURCE'), reason='Requires one explicit actual LAS path')
def test_actual_las_polygon_preview_read_only(window, tmp_path):
    source = Path(os.environ['LIDAR_POLYGON_SMOKE_SOURCE']).resolve()
    before = file_sha256(source)
    state = source.stat()
    start = perf_counter()
    open_cloud(window, source)
    open_seconds = perf_counter() - start
    assert window.doc.count > 250_000 and len(window.coords) == 250_000
    window.set_view('top')
    window.projection_combo.setCurrentIndex(1)
    overlay = begin(window)
    window.use_box.setChecked(False)
    rectangle(overlay, .15, .15, .54, .85)
    start = perf_counter()
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    preview_seconds = perf_counter() - start
    count = window.plotter.renderer.actors['selected'].mapper.dataset.n_points
    assert 0 < count < len(window.coords)
    assert 'Full retained:' not in window.stat_label.text()
    window.plotter.screenshot(tmp_path / 'real_polygon_preview.png')
    assert source.stat().st_size == state.st_size and source.stat().st_mtime_ns == state.st_mtime_ns
    assert file_sha256(source) == before
    print(f'GUI actual read-only: {window.doc.count:,} source, {count:,}/{len(window.coords):,} preview; '
          f'open {open_seconds:.3f}s, confirm + render {preview_seconds:.3f}s, '
          f'peak {peak_rss_mib():.1f} MiB. {tmp_path}')
