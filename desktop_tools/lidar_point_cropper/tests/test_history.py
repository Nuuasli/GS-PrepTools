import json

import laspy
import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from lidar_cropper.core import HISTORY_SCHEMA, BoxSelection, CropError, axis_aligned_box, export_crop, file_sha256, load_cloud
from lidar_cropper.history import SelectionHistory, load_history_json, save_history_json
from tests.test_polygon import expected_points, sample_points, sample_selection


def test_box_keep_remove_reset_history_replays_both_directions():
    points = sample_points()
    plan = sample_selection()
    root = axis_aligned_box(-4, 4, -4, 4, -3, 3)
    history = SelectionHistory(root, 'OBB')
    assert not history.undo() and not history.redo()
    expected = [history.selection.mask(points)]
    history.set_box(plan.initial_box, 'AABB')
    expected.append(history.selection.mask(points))
    for op in plan.operations:
        history.apply_polygon(op)
        expected.append(history.selection.mask(points))
    np.testing.assert_array_equal(expected[-1], expected_points(points))
    history.current.full_count = int(expected[-1].sum())
    history.set_box(root, 'OBB', reset=True)
    expected.append(expected[0])
    assert history.current.action == 'reset'
    for index in range(3, -1, -1):
        assert history.undo() and history.position == index
        np.testing.assert_array_equal(history.selection.mask(points), expected[index])
        assert history.current.full_count == (int(expected[3].sum()) if index == 3 else None)
    assert not history.undo()
    for index in range(1, 5):
        assert history.redo() and history.position == index
        np.testing.assert_array_equal(history.selection.mask(points), expected[index])
    assert not history.redo()


def test_undo_redo_oriented_box_and_new_edit_discards_redo_branch():
    points = sample_points()
    root = axis_aligned_box(-4, 4, -4, 4, -3, 3)
    small = axis_aligned_box(-2, 2, -.75, .75, -.75, .75)
    angle = np.pi / 4
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                         [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    obb = BoxSelection.from_planes(small.origins @ rotation.T, small.normals @ rotation.T)
    history = SelectionHistory(root, 'AABB')
    history.set_box(obb, 'OBB')
    rotated_mask = obb.mask(points)
    assert history.undo() and history.current.box_mode == 'AABB'
    assert history.redo() and history.current.box_mode == 'OBB'
    np.testing.assert_array_equal(history.selection.mask(points), rotated_mask)
    history.undo()
    history.set_box(small, 'AABB')
    assert not history.can_redo and history.length == 2
    np.testing.assert_array_equal(history.selection.mask(points), small.mask(points))


@pytest.mark.parametrize(('source_ext', 'output_ext'), [('las', 'laz'), ('laz', 'las'), ('ply', 'ply')])
def test_save_and_export_current_position_after_undo(tmp_path, source_ext, output_ext):
    xyz = sample_points()
    source = tmp_path / f'source.{source_ext}'
    if source_ext == 'ply':
        records = np.zeros(len(xyz), dtype=[('x', '<f8'), ('y', '<f8'), ('z', '<f8'), ('f_dc_0', '<f4')])
        records['x'], records['y'], records['z'] = xyz.T
        records['f_dc_0'] = np.linspace(0, 1, len(xyz))
        PlyData([PlyElement.describe(records, 'vertex')]).write(source)
    else:
        las = laspy.create(point_format=3)
        las.x, las.y, las.z = xyz.T
        las.intensity = np.arange(len(xyz)) * 6
        las.gps_time = np.arange(len(xyz)) / 3
        las.blue = np.arange(len(xyz)) * 10
        las.write(source)
        records = las.points.array
    original = file_sha256(source)
    doc = load_cloud(source)
    plan = sample_selection()
    history = SelectionHistory(plan.initial_box, 'AABB')
    history.apply_polygon(plan.operations[0])
    history.apply_polygon(plan.operations[1])
    assert history.undo() and history.can_redo
    expected = (xyz[:, 0] >= -2) & (xyz[:, 0] <= 0) & (xyz[:, 2] == 0)
    preview, _ = doc.preview(4)
    assert history.selection.mask(preview).sum() < expected.sum()
    snapshot = history.snapshot()
    assert snapshot['position'] == 1
    assert [step['action'] for step in snapshot['steps']] == ['initial', 'keep']
    save_path = save_history_json(tmp_path / 'selection.json', doc, history.selection, snapshot, None)
    saved = json.loads(save_path.read_text('utf-8'))
    assert saved['schema_version'] == HISTORY_SCHEMA and saved['retained_points'] is None
    reloaded = load_history_json(save_path, doc)
    assert reloaded.can_undo and not reloaded.can_redo
    np.testing.assert_array_equal(reloaded.selection.mask(xyz), expected)
    out, export_meta, _ = export_crop(doc, history.selection, tmp_path / f'crop.{output_ext}',
                                      selection_history=snapshot)
    actual = (PlyData.read(out)['vertex'].data if output_ext == 'ply' else laspy.read(out).points.array)
    assert actual.tobytes() == records[expected].tobytes()
    assert load_history_json(export_meta, doc).current.full_count == expected.sum()
    assert file_sha256(source) == original
    saved['input_sha256'] = 'f' * 64
    save_path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(CropError, match='SHA-256'):
        load_history_json(save_path, doc)


def test_many_steps_serialise_one_operation_each():
    plan = sample_selection()
    history = SelectionHistory(plan.initial_box, 'AABB')
    for _ in range(200):
        history.apply_polygon(plan.operations[0])
    snapshot = history.snapshot()
    assert len(snapshot['steps']) == 201 and len(history.selection.operations) == 200
    assert len(json.dumps(snapshot).encode()) < 240_000
    assert all(step['geometry']['operation'] == 'keep' for step in snapshot['steps'][1:])
