"""Qt mouse-event tests for brush drawing, history and one optional actual LAS."""
import json
import os
from pathlib import Path
from statistics import median
from threading import Event
from time import perf_counter
from unittest.mock import patch

import laspy
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from lidar_cropper.core import CropCancelled, file_sha256
from lidar_cropper.gui import BrushPreviewTask
from tests.gui_history_smoke import assert_preview
from tests.gui_las_smoke import build_fixture, peak_rss_mib
from tests.gui_polygon_smoke import LEFT, begin, open_cloud, rectangle, window
from tests.gui_smoke import wait_until


def start_brush(window, *, restore=False, radius=32):
    QTest.mouseClick(window.brush_toggle, LEFT)
    assert window.brush_overlay.camera is not None, window.statusBar().currentMessage()
    window.brush_mode.setCurrentIndex(int(restore))
    window.brush_radius.setValue(radius)
    return window.brush_overlay


def draw(overlay, start=(.39, .5), end=(.61, .5)):
    def point(uv):
        return QPoint(round(uv[0] * overlay.width()), round(uv[1] * overlay.height()))

    QTest.mousePress(overlay, LEFT, pos=point(start))
    for weight in (.25, .5, .75, 1.):
        QTest.mouseMove(overlay, point(tuple(a + weight * (b - a) for a, b in zip(start, end))))
    release = perf_counter()
    QTest.mouseRelease(overlay, LEFT, pos=point(end))
    return release


def wait_for_preview(window):
    if window.task is None:
        return
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if window.task is None else None)
    timer.start(10)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(15000)
    loop.exec()
    assert window.task is None, 'Timed out waiting for brush preview'


def test_brush_gui_mixed_replay(window, tmp_path):
    source = build_fixture(tmp_path / 'brush_input.laz')
    original_hash = file_sha256(source)
    open_cloud(window, source)
    window.plotter.camera_position = [(0, 0, 10), (0, 0, 0), (0, 1, 0)]
    window.plotter.reset_camera_clipping_range()
    window.plotter.render()
    QTest.qWait(100)

    polygon = begin(window)
    rectangle(polygon, .20, .20, .75, .80)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    before = window.roi.mask(window.coords)
    front_pose = window.plotter.camera_position
    history_position = window.history.position
    overlay = start_brush(window)
    window.set_view('left')
    assert window.plotter.camera_position == front_pose
    draw(overlay)
    wait_until(lambda: window.task is None)
    assert len(overlay.points) > 2 and 'brush_hit' in window.plotter.renderer.actors
    assert window.confirm_stroke_btn.isEnabled()
    assert window.history.position == history_position
    np.testing.assert_array_equal(window.roi.mask(window.coords), before)
    assert overlay.grab().save(str(tmp_path / 'stroke_draft.png'))
    QTest.mouseClick(window.confirm_stroke_btn, LEFT)
    after_remove = window.roi.mask(window.coords)
    assert 0 < after_remove.sum() < before.sum()
    assert window.history.position == history_position + 1 and overlay.camera is None
    assert_preview(window, after_remove)

    window.set_view('left')
    window.projection_combo.setCurrentIndex(1)
    overlay = start_brush(window, restore=True, radius=330)
    draw(overlay, (.41, .5), (.62, .5))
    wait_until(lambda: window.task is None)
    assert window._brush_draft[2] > 0
    QTest.mouseClick(window.confirm_stroke_btn, LEFT)
    restored = window.roi.mask(window.coords)
    assert after_remove.sum() < restored.sum() <= before.sum() and not np.any(restored & ~before)
    assert window.roi.operations[-2].camera.mode == 'perspective'
    assert window.roi.operations[-1].camera.mode == 'orthographic'
    QTest.mouseClick(window.undo_btn, LEFT)
    wait_until(lambda: window.task is None)
    assert_preview(window, after_remove)
    QTest.mouseClick(window.redo_btn, LEFT)
    wait_until(lambda: window.task is None)
    assert_preview(window, restored)

    overlay = start_brush(window)
    draw(overlay)
    wait_until(lambda: window.task is None)
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    wait_until(lambda: overlay.camera is None)
    assert window.history.position == history_position + 2
    assert_preview(window, restored)

    out = tmp_path / 'brush_crop.las'
    with (
        patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out), '')),
        patch.object(QMessageBox, 'information') as success,
    ):
        QTest.mouseClick(window.export_btn, LEFT)
        wait_until(lambda: window.task is None, timeout=30)
        success.assert_called_once()
    assert laspy.read(out).points.array.tobytes() == laspy.read(source).points.array[restored].tobytes()
    assert file_sha256(source) == original_hash
    meta = out.with_name('brush_crop_selection.json')
    assert json.loads(meta.read_text('utf-8'))['schema_version'] == 5
    overlay = start_brush(window)
    old = window.plotter.interactor.size()
    window.showNormal()
    window.resize(1240, 760)
    wait_until(lambda: window.plotter.interactor.size() != old and overlay.camera is None)
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(meta), '')):
        QTest.mouseClick(window.load_roi_btn, LEFT)
        wait_until(lambda: window.task is None)
    assert_preview(window, restored)
    print(f'Synthetic brush GUI: removed {before.sum()-after_remove.sum():,}, restored '
          f'{restored.sum()-after_remove.sum():,}, exported {restored.sum():,}, '
          f'DPR {window.plotter.interactor.devicePixelRatioF()}. {tmp_path}')


def test_export_cancel_button(window, tmp_path):
    source = build_fixture(tmp_path / 'cancel_input.las')
    open_cloud(window, source)
    QTest.mouseClick(window.preview_btn, LEFT)
    entered = Event()
    out = tmp_path / 'cancelled.laz'

    def simulated_slow_export(*args, cancelled, **kwargs):
        entered.set()
        for _ in range(300):
            if cancelled():
                raise CropCancelled()
            Event().wait(.01)
        raise RuntimeError('Export was not cancelled')

    with (
        patch('lidar_cropper.gui.export_crop', side_effect=simulated_slow_export),
        patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out), '')),
    ):
        QTest.mouseClick(window.export_btn, LEFT)
        wait_until(entered.is_set)
        assert window.cancel_export_btn.isVisible()
        QTest.mouseClick(window.cancel_export_btn, LEFT)
        wait_until(lambda: window.task is None)
    assert not out.exists() and not window.cancel_export_btn.isVisible()
    assert window.progress_label.text() == 'Cancelled'
    assert window.export_btn.isEnabled()


@pytest.mark.skipif(not os.environ.get('LIDAR_BRUSH_SMOKE_SOURCE'), reason='Requires one existing LAS')
def test_brush_actual_preview_only(window, tmp_path, monkeypatch):
    source = Path(os.environ['LIDAR_BRUSH_SMOKE_SOURCE']).resolve()
    digest = file_sha256(source)
    stamp = source.stat().st_mtime_ns
    open_cloud(window, source)
    assert window.doc.count > 5_000_000 and len(window.coords) == 250_000
    window.set_view('top')
    window.projection_combo.setCurrentIndex(1)
    before = window.roi.mask(window.coords)
    worker_ms = []
    run_preview = BrushPreviewTask.run

    def timed_worker(task):
        start = perf_counter()
        run_preview(task)
        worker_ms.append((perf_counter() - start) * 1000)

    monkeypatch.setattr(BrushPreviewTask, 'run', timed_worker)
    overlay = start_brush(window, radius=28)
    release = draw(overlay, (.45, .49), (.55, .52))
    wait_for_preview(window)
    preview_time = perf_counter() - release
    assert window._brush_draft[2] > 0
    start = perf_counter()
    QTest.mouseClick(window.confirm_stroke_btn, LEFT)
    confirm_time = perf_counter() - start
    after = window.roi.mask(window.coords)
    assert 0 < after.sum() < before.sum()
    undo, redo = [], []
    for _ in range(5):
        for samples, button, expected in ((undo, window.undo_btn, before), (redo, window.redo_btn, after)):
            start = perf_counter()
            QTest.mouseClick(button, LEFT)
            wait_for_preview(window)
            samples.append(perf_counter() - start)
            assert_preview(window, expected)
    window.plotter.screenshot(tmp_path / 'actual_brush_preview.png')
    assert file_sha256(source) == digest and source.stat().st_mtime_ns == stamp
    assert 'Full retained:' not in window.stat_label.text()
    print(f'Actual brush GUI read-only: {window.doc.count:,} source, {before.sum()-after.sum():,} '
          f'removed from {len(before):,} preview, release to preview {preview_time*1000:.1f} ms, '
          f'confirm {confirm_time*1000:.1f} ms, median Undo {median(undo)*1000:.1f} ms, '
          f'Redo {median(redo)*1000:.1f} ms, process peak {peak_rss_mib():.1f} MiB. {tmp_path}')
    print('Sample mask worker times (ms):', [round(value, 1) for value in worker_ms])
