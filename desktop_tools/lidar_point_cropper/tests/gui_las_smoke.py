"""Run explicitly on Windows. Set LIDAR_SMOKE_SOURCE for one real LAS/LAZ."""

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import laspy
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from lidar_cropper.core import box_corners, file_sha256
from lidar_cropper.gui import CropperWindow
from tests.gui_smoke import display_position, drag, wait_until


def peak_rss_mib():
    class Memory(ctypes.Structure):
        _fields_ = [
            ('size', wintypes.DWORD), ('faults', wintypes.DWORD),
            ('peak_working_set', ctypes.c_size_t), ('remaining', ctypes.c_size_t * 7),
        ]

    counters = Memory()
    counters.size = ctypes.sizeof(counters)
    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    if not get_memory(get_process(), ctypes.byref(counters), counters.size):
        raise ctypes.WinError()
    return counters.peak_working_set / 2**20


def build_fixture(path):
    rng = np.random.default_rng(87)
    xyz = rng.uniform(-3., 3., (7000, 3))
    las = laspy.create(point_format=3, file_version='1.2')
    las.header.scales = np.full(3, .001)
    las.x, las.y, las.z = xyz.T
    las.intensity = rng.integers(0, 65536, len(xyz), dtype=np.uint16)
    las.red = las.intensity
    las.green = np.full(len(xyz), 32768)
    las.blue = np.full(len(xyz), 16384)
    las.classification = np.full(len(xyz), 3)
    las.write(path)
    return path


def verify_full_export(source, output, selection):
    origins = selection['origins']
    normals = selection['normals_outward']
    count = 0
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    with laspy.open(source) as original, laspy.open(output) as written:
        assert original.header.point_format == written.header.point_format
        np.testing.assert_array_equal(original.header.scales, written.header.scales)
        np.testing.assert_array_equal(original.header.offsets, written.header.offsets)
        for chunk in original.chunk_iterator(128_000):
            xyz = np.column_stack((chunk.x, chunk.y, chunk.z))
            mask = np.ones(len(chunk), dtype=bool)
            for origin, normal in zip(origins, normals):
                mask &= np.einsum('ij,j->i', xyz - origin, normal) <= 1e-7
            sample = xyz[mask]
            if len(sample):
                saved = written.read_points(len(sample))
                assert saved.array.tobytes() == chunk.array[mask].tobytes()
                low = np.minimum(low, sample.min(axis=0))
                high = np.maximum(high, sample.max(axis=0))
                count += len(sample)
        assert 0 < count == written.header.point_count < original.header.point_count
        assert len(written.read_points(1)) == 0
        np.testing.assert_array_equal(written.header.mins, low)
        np.testing.assert_array_equal(written.header.maxs, high)
    return count


def test_windows_las_gui(tmp_path, monkeypatch):
    path = os.environ.get('LIDAR_SMOKE_SOURCE')
    source = Path(path).resolve() if path else build_fixture(tmp_path / 'synthetic.laz')
    source_stamp = source.stat()
    original_hash = file_sha256(source)
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows'
    window = CropperWindow()
    window.showMaximized()
    click = Qt.MouseButton.LeftButton
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[2]))

    def place_small_box(center, half):
        bounds = np.column_stack((center - half, center + half)).ravel()
        span = float(max(half))
        window.plotter.camera_position = [
            (center + [0, 0, span * 7]).tolist(), center.tolist(), [0, 1, 0],
        ]
        window.plotter.camera.parallel_projection = True
        window.plotter.camera.parallel_scale = span * 1.7
        window.plotter.camera.clipping_range = (span * .05, span * 20)
        window.plotter.clear_box_widgets()
        window.box_widget = window.plotter.add_box_widget(
            callback=window._box_changed, bounds=bounds.tolist(), factor=1.,
            use_planes=True, rotation_enabled=(window.mode_combo.currentIndex() == 0),
            outline_translation=True, interaction_event='end',
        )
        window.plotter.render()
        QTest.qWait(120)
        return box_corners(window.roi)

    try:
        assert QTest.qWaitForWindowExposed(window)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
            start = perf_counter()
            QTest.mouseClick(window.open_btn, click)
            wait_until(lambda: window.task is None, timeout=120)
        assert window.doc is not None and not errors, errors
        window.plotter.screenshot(tmp_path / 'viewport.png')
        load_seconds = perf_counter() - start
        assert len(window.coords) == min(250_000, window.doc.count)
        original = window.plotter.renderer.actors['original'].mapper.dataset
        assert original.n_points == len(window.coords)
        color = window.color_combo.currentText()
        if window.doc.rgb_status == 'all_zero':
            assert color in ('Intensity', 'Elevation')
            assert ('strength' if color == 'Intensity' else 'height') in original.point_data
        elif not path:
            assert color == 'RGB'
            np.testing.assert_array_equal(original['color'][0, 1:], [128, 64])

        lo, mid, hi = np.quantile(window.coords, [.1, .5, .9], axis=0)
        center = window.coords[np.argmin(np.linalg.norm(window.coords - mid, axis=1))]
        half = np.maximum((hi - lo) * .07, (hi - lo).max() * .016)
        viewport = window.plotter.interactor
        window.mode_combo.setCurrentIndex(1)
        before = place_small_box(center, half)
        face = [before[:, 0].min(), center[1], center[2]]
        drag(viewport, click, display_position(window, face), QPoint(40, 0))
        after = box_corners(window.roi)
        assert after[:, 0].min() > before[:, 0].min()
        np.testing.assert_allclose(np.max(np.abs(window.roi.normals), axis=1), 1.)
        QTest.mouseClick(window.preview_btn, click)
        aabb_count = int(window.roi.mask(window.coords).sum())
        assert aabb_count > 0
        assert window.plotter.renderer.actors['selected'].mapper.dataset.n_points == aabb_count

        window.mode_combo.setCurrentIndex(0)
        before = place_small_box(center, half)
        face = [center[0] + .45 * half[0], center[1] + .45 * half[1], before[:, 2].max()]
        drag(viewport, click, display_position(window, face), QPoint(48, 34))
        assert np.any(np.max(np.abs(window.roi.normals), axis=1) < .999)
        QTest.mouseClick(window.preview_btn, click)
        preview_mask = window.roi.mask(window.coords)
        assert preview_mask.any() and window.export_btn.isEnabled()
        window.show_original.setChecked(False)
        window.plotter.screenshot(tmp_path / 'obb_preview.png')

        destination = tmp_path / ('real_crop.laz' if path else 'synthetic_crop.las')
        with (
            patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), '')),
            patch.object(QMessageBox, 'information') as confirmed,
        ):
            start = perf_counter()
            QTest.mouseClick(window.export_btn, click)
            wait_until(lambda: window.task is None, timeout=120)
            export_seconds = perf_counter() - start
            assert not errors, errors
            confirmed.assert_called_once()

        metadata = destination.with_name(destination.stem + '_selection.json')
        saved = json.loads(metadata.read_text('utf-8'))
        assert saved['source_points'] == window.doc.count
        assert saved['roi_kind'] == 'OBB'
        count = verify_full_export(source, destination, saved['selection'])
        assert count == saved['retained_points']
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(metadata), '')):
            QTest.mouseClick(window.load_roi_btn, click)
        assert window.roi_locked and not errors, errors
        QTest.mouseClick(window.preview_btn, click)
        np.testing.assert_array_equal(window.roi.mask(window.coords), preview_mask)
        assert window.plotter.renderer.actors['selected'].mapper.dataset.n_points == preview_mask.sum()
        current = source.stat()
        assert (current.st_size, current.st_mtime_ns) == (source_stamp.st_size, source_stamp.st_mtime_ns)
        assert file_sha256(source) == saved['input_sha256'] == original_hash
        print(f'Input {window.doc.count:,}; preview {len(window.coords):,}; '
              f'AABB preview {aabb_count:,}; OBB preview {preview_mask.sum():,}; '
              f'export {count:,}; RGB {window.doc.rgb_status}; color mode {color}.\n'
              f'Open to rendered viewport {load_seconds:.3f}s; full export {export_seconds:.3f}s; '
              f'peak process working set {peak_rss_mib():.1f} MiB.\n'
              f'SHA-256 {original_hash}\nOutputs: {tmp_path}')
    finally:
        wait_until(lambda: window.task is None, timeout=120)
        window.close()
        app.processEvents()
        assert not window.isVisible()
