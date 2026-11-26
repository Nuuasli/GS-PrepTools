"""Run explicitly on Windows. The actual LAS case only exercises the preview."""
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch

import laspy
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from lidar_cropper.core import box_corners, file_sha256
from tests.gui_las_smoke import build_fixture, peak_rss_mib
from tests.gui_polygon_smoke import LEFT, begin, open_cloud, rectangle, window
from tests.gui_smoke import display_position, drag, wait_until


def current_mask(window):
    return window.roi.mask(window.coords)


def assert_preview(window, expected):
    np.testing.assert_array_equal(current_mask(window), expected)
    assert window.preview_active
    count = int(expected.sum())
    assert f'Preview selected: {count:,} /' in window.stat_label.text()
    actor = window.plotter.renderer.actors.get('selected')
    assert (actor.mapper.dataset.n_points if actor is not None else 0) == count


def test_history_gui(window, tmp_path):
    source = build_fixture(tmp_path / 'synthetic.laz')
    original_hash = file_sha256(source)
    open_cloud(window, source)
    assert not window.undo_btn.isEnabled() and not window.redo_btn.isEnabled()
    window.mode_combo.setCurrentIndex(1)
    window.set_view('top')
    initial_aabb = current_mask(window)
    bounds = box_corners(window.roi)
    center = bounds.mean(axis=0)
    face = [bounds[:, 0].min(), center[1], center[2]]
    viewport = window.plotter.interactor
    position = window.history.position
    drag(viewport, LEFT, display_position(window, face), QPoint(65, 0))
    aabb = current_mask(window)
    assert aabb.sum() < initial_aabb.sum()
    assert window.history.position == position + 1
    QTest.keyClick(viewport, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert_preview(window, initial_aabb)
    QTest.mouseClick(window.redo_btn, LEFT)
    assert_preview(window, aabb)
    window.mode_combo.setCurrentIndex(0)
    window.set_view('top')
    initial_obb = current_mask(window)
    bounds = box_corners(window.roi)
    center = bounds.mean(axis=0)
    face = [center[0] + .8, center[1] + .8, bounds[:, 2].max()]
    drag(viewport, LEFT, display_position(window, face), QPoint(70, 45))
    obb = current_mask(window)
    obb_corners = box_corners(window.roi)
    assert np.any(np.max(np.abs(window.roi.normals), axis=1) < .999)
    QTest.mouseClick(window.undo_btn, LEFT)
    assert_preview(window, initial_obb)
    QTest.keyClick(viewport, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert_preview(window, obb)
    actual_corners = box_corners(window._vtk_box_planes(window.box_widget))
    distances = np.linalg.norm(obb_corners[:, None] - actual_corners[None, :], axis=2)
    assert distances.min(axis=1).max() < 1e-5

    overlay = begin(window)
    assert not window.undo_btn.isEnabled() and not window.redo_shortcut.isEnabled()
    rectangle(overlay, .29, .18, .58, .79)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    keep = current_mask(window)
    assert 0 < keep.sum() < obb.sum()
    window.set_view('left')
    overlay = begin(window, 'remove')
    rectangle(overlay, .48, .44, .56, .60)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    removed = current_mask(window)
    assert 0 < removed.sum() < keep.sum()

    QTest.mouseClick(window.undo_btn, LEFT)
    assert_preview(window, keep)
    assert window.redo_btn.isEnabled()
    assert 'Full retained:' not in window.stat_label.text()
    saved = tmp_path / 'active_selection.json'
    with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(saved), '')):
        QTest.mouseClick(window.save_roi_btn, LEFT)
        wait_until(lambda: window.task is None)
    metadata = json.loads(saved.read_text('utf-8'))
    assert metadata['retained_points'] is None
    assert metadata['selection_history']['steps'][-1]['action'] == 'keep'
    assert not any(step['action'] == 'remove' for step in metadata['selection_history']['steps'])
    out = tmp_path / 'crop_after_undo.las'
    with (
        patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out), '')),
        patch.object(QMessageBox, 'information') as success,
    ):
        QTest.mouseClick(window.export_btn, LEFT)
        wait_until(lambda: window.task is None)
        success.assert_called_once()
    assert laspy.read(out).points.array.tobytes() == laspy.read(source).points.array[keep].tobytes()
    assert f'Full retained: {keep.sum():,}' in window.stat_label.text()
    QTest.mouseClick(window.redo_btn, LEFT)
    assert_preview(window, removed)
    assert 'Full retained:' not in window.stat_label.text()
    QTest.mouseClick(window.undo_btn, LEFT)
    QTest.mouseClick(window.reset_btn, LEFT)
    assert window.history.current.action == 'reset'
    assert not window.redo_btn.isEnabled() and window.undo_btn.isEnabled()
    QTest.mouseClick(window.undo_btn, LEFT)
    assert_preview(window, keep)
    assert f'Full retained: {keep.sum():,}' in window.stat_label.text()
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(saved), '')):
        QTest.mouseClick(window.load_roi_btn, LEFT)
    assert_preview(window, keep)
    assert window.undo_btn.isEnabled() and not window.redo_btn.isEnabled()
    assert 'Full retained:' not in window.stat_label.text()
    assert file_sha256(source) == original_hash
    print(f'Synthetic GUI: AABB {aabb.sum()}, OBB {obb.sum()}, Keep {keep.sum()}, '
          f'after Remove {removed.sum()}, export after Undo {keep.sum()}. {tmp_path}')


@pytest.mark.skipif(not os.environ.get('LIDAR_HISTORY_SMOKE_SOURCE'), reason='Requires one existing LAS path')
def test_history_actual_las_preview_only(window, tmp_path):
    source = Path(os.environ['LIDAR_HISTORY_SMOKE_SOURCE']).resolve()
    before_hash, before_stamp = file_sha256(source), source.stat()
    open_cloud(window, source)
    assert window.doc.count > 5_000_000 and len(window.coords) == 250_000
    window.set_view('top')
    window.projection_combo.setCurrentIndex(1)
    initial_mask = current_mask(window)
    baseline = peak_rss_mib()
    overlay = begin(window)
    window.use_box.setChecked(False)
    rectangle(overlay, .15, .15, .54, .85)
    QTest.mouseClick(window.confirm_polygon_btn, LEFT)
    kept = current_mask(window)
    assert 0 < kept.sum() < len(kept)
    undo_times, redo_times = [], []
    for _ in range(10):
        start = perf_counter()
        QTest.mouseClick(window.undo_btn, LEFT)
        undo_times.append(perf_counter() - start)
        assert_preview(window, initial_mask)
        start = perf_counter()
        QTest.mouseClick(window.redo_btn, LEFT)
        redo_times.append(perf_counter() - start)
        assert_preview(window, kept)
        assert window.history.length == 2
    assert 'Full retained:' not in window.stat_label.text()
    window.plotter.screenshot(tmp_path / 'history_actual_preview.png')
    assert file_sha256(source) == before_hash
    after = source.stat()
    assert (after.st_size, after.st_mtime_ns) == (before_stamp.st_size, before_stamp.st_mtime_ns)
    history_bytes = len(json.dumps(window.history.snapshot()).encode('utf-8'))
    print(f'Actual GUI preview: {window.doc.count:,} source, {initial_mask.sum():,} to {kept.sum():,} sample, '
          f'median Undo {median(undo_times)*1000:.1f} ms, Redo {median(redo_times)*1000:.1f} ms. '
          f'Process peak {baseline:.1f} to {peak_rss_mib():.1f} MiB, geometry history JSON {history_bytes:,} bytes. '
          f'{tmp_path}')
