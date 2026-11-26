import json

import laspy
import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from lidar_cropper import core, las
from lidar_cropper.brush import BrushOperation, BrushSelection
from lidar_cropper.core import CropCancelled, CropError, export_crop, file_sha256, load_cloud
from lidar_cropper.history import SelectionHistory, load_history_json, save_history_json
from lidar_cropper.polygon import PolygonOperation
from tests.test_polygon import FULL_VIEW, camera_state, sample_points, sample_selection


@pytest.mark.parametrize('parallel', [True, False])
def test_stroke_capsule_radius_and_clipping(parallel):
    camera, _, _ = camera_state(parallel=parallel)
    # At z=0, one source unit spans 100 px orthographic or 40 px perspective.
    pixels_per_unit = 100 if parallel else 40
    radius = 10
    boundary = radius / pixels_per_unit
    points = np.array([[0, boundary, 0], [0, boundary + .01, 0],
                       [0, 0, 5], [0, 0, 11], [0, 0, -11], [100, 0, 0]])
    stroke = BrushOperation('brush_remove', ((.4, .5), (.6, .5)), radius, camera, (9., 11.))
    assert stroke.mask(points).tolist() == [True, False, False, False, False, False]
    wide = BrushOperation('brush_remove', stroke.points_uv, 20, camera, (0, 40))
    assert wide.mask(points).tolist() == [True, True, True, False, False, False]
    disk = BrushOperation('brush_remove', ((.5, .5),), radius, camera, (9., 11.))
    assert disk.mask(np.array([[boundary, 0, 0], [boundary + .01, 0, 0]])).tolist() == [True, False]


def test_dpr_scaling_and_replay_uses_original_framebuffer():
    base, _, _ = camera_state(size=(800, 800))
    hidpi, _, _ = camera_state(size=(1600, 1600), dpr=2.)
    points = np.array([[.24, 0, 0], [.25, 0, 0], [.26, 0, 0]])
    stroke = BrushOperation('brush_remove', ((.5, .5),), 25, base, (9, 11))
    high = BrushOperation('brush_remove', stroke.points_uv, 25, hidpi, (9, 11))
    replay = BrushOperation.from_dict(json.loads(json.dumps(high.to_dict())))
    assert stroke.mask(points).tolist() == [True, True, False]
    np.testing.assert_array_equal(replay.mask(points), stroke.mask(points))


def test_invalid_stroke():
    camera, _, _ = camera_state()
    for points, radius, depth in [((), 20, (1, 2)), (((2, .2),), 30, (1, 2)),
                                  (((.2, .2),), 0, (1, 2)), (((.2, .2),), 30, (3, 2))]:
        with pytest.raises(CropError):
            BrushOperation('brush_restore', points, radius, camera, depth)


def mixed_history():
    polygon = sample_selection()
    front = polygon.operations[0].camera
    history = SelectionHistory(polygon.initial_box, 'AABB')
    history.apply_polygon(polygon.operations[0])
    history.apply_brush(BrushOperation('brush_remove', ((.375, .25), (.375, .75)), 37, front, (9.5, 10.5)))
    # Top/side projection at y=10, x flips sign; depth 10 restores y=0.
    side = polygon.operations[1].camera
    history.apply_brush(BrushOperation('brush_restore', ((.625, .5),), 400, side, (9.5, 10.5)))
    return history


def analytic_mask(xyz, restored=True):
    x, y, z = xyz.T
    active = ((x == -2) | (x == 0)) & (z == 0)
    if restored:
        active |= (x == -1) & (y == 0) & (z == 0)
    return active


def test_mixed_history_restore_domain_and_branch():
    points = sample_points()
    history = mixed_history()
    assert isinstance(history.selection, BrushSelection)
    np.testing.assert_array_equal(history.selection.mask(points), analytic_mask(points))
    assert history.undo()
    np.testing.assert_array_equal(history.selection.mask(points), analytic_mask(points, False))
    assert history.redo()
    np.testing.assert_array_equal(history.selection.mask(points), analytic_mask(points))
    history.undo()
    side = sample_selection().operations[1].camera
    history.apply_polygon(PolygonOperation('remove', FULL_VIEW, side, (9.5, 10.5)))
    history.apply_brush(BrushOperation('brush_restore', ((.5, .5),), 400, side, (7., 13.)))
    active = history.selection.mask(points)
    assert not history.can_redo
    # Restore cannot cross the initial box, undo either polygon decision, or revive hidden layers.
    x, y, z = points.T
    np.testing.assert_array_equal(active, (x >= -2) & (x <= 0) & (y != 0) & (z == 0))


@pytest.mark.parametrize(('input_ext', 'output_ext'), [('ply', 'ply'), ('las', 'laz'), ('laz', 'las')])
def test_brush_full_resolution_round_trip_cancel_and_hash(tmp_path, monkeypatch, input_ext, output_ext):
    monkeypatch.setattr(core, 'CHUNK_SIZE', 7)
    monkeypatch.setattr(las, 'CHUNK_SIZE', 7)
    xyz = sample_points()
    path = tmp_path / f'original.{input_ext}'
    if input_ext == 'ply':
        records = np.zeros(len(xyz), dtype=[('x', '<f8'), ('y', '<f8'), ('z', '<f8'),
                                            ('f_dc_0', '<f4'), ('scale_0', '<f4')])
        records['x'], records['y'], records['z'] = xyz.T
        records['f_dc_0'] = np.linspace(0, 1, len(xyz))
        records['scale_0'] = np.linspace(-5, 3, len(xyz))
        PlyData([PlyElement.describe(records, 'vertex')]).write(path)
    else:
        source = laspy.create(point_format=3, file_version='1.2')
        source.header.scales, source.header.offsets = np.array([.01, .02, .005]), np.array([10., -20., 30.])
        source.x, source.y, source.z = xyz.T
        rows = np.arange(len(xyz))
        source.intensity, source.gps_time = rows * 21, rows + .25
        source.red, source.green, source.blue = rows * 33, rows * 29, rows * 17
        source.classification, source.return_number = rows % 7, rows % 3 + 1
        source.write(path)
        records = source.points.array
    history = mixed_history()
    doc = load_cloud(path)
    before = file_sha256(path)
    output = tmp_path / f'crop.{output_ext}'
    expect = analytic_mask(xyz)
    sample, _ = doc.preview(4)
    assert history.selection.mask(sample).sum() < expect.sum()
    progress = []
    with pytest.raises(CropCancelled):
        export_crop(doc, history.selection, output, progress=progress.append,
                    cancelled=lambda: bool(progress) and progress[-1] >= 60)
    assert not output.exists() and not list(tmp_path.glob('.crop-*'))
    assert not (tmp_path / 'crop_selection.json').exists()
    output, meta, result = export_crop(doc, history.selection, output, selection_history=history.snapshot())
    if input_ext == 'ply':
        actual = PlyData.read(output)['vertex'].data
    else:
        cropped = laspy.read(output)
        np.testing.assert_array_equal(cropped.header.scales, source.header.scales)
        np.testing.assert_array_equal(cropped.header.offsets, source.header.offsets)
        actual = cropped.points.array
    assert actual.dtype == records.dtype and actual.tobytes() == records[expect].tobytes()
    assert result['schema_version'] == 5 and result['retained_points'] == expect.sum()
    assert result['input_sha256'] == file_sha256(path) == before
    np.testing.assert_array_equal(load_history_json(meta, doc).selection.mask(xyz), expect)
    result['input_sha256'] = '0' * 64
    meta.write_text(json.dumps(result), encoding='utf-8')
    with pytest.raises(CropError, match='SHA-256'):
        load_history_json(meta, doc)


def test_schema_four_replay_legacy_poly(tmp_path):
    path = tmp_path / 'legacy.ply'
    records = np.zeros(4, dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4')])
    PlyData([PlyElement.describe(records, 'vertex')]).write(path)
    doc = load_cloud(path)
    plan = sample_selection()
    history = SelectionHistory(plan.initial_box, 'AABB')
    history.apply_polygon(plan.operations[0])
    meta = save_history_json(tmp_path / 'legacy.json', doc, history.selection, history.snapshot(), None)
    data = json.loads(meta.read_text('utf-8'))
    data['schema_version'] = 4
    meta.write_text(json.dumps(data), encoding='utf-8')
    np.testing.assert_array_equal(load_history_json(meta, doc).selection.mask(sample_points()),
                                  history.selection.mask(sample_points()))
