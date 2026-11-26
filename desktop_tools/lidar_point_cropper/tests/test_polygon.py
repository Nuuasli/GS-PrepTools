import json

import laspy
import numpy as np
import pytest
import vtk
from plyfile import PlyData, PlyElement

from lidar_cropper import core
from lidar_cropper.core import CropError, axis_aligned_box, export_crop, file_sha256, load_cloud, load_selection_json
from lidar_cropper.polygon import CameraProjection, PolygonOperation, PolygonSelection, screen_to_uv, uv_to_screen


FULL_VIEW = [(0., 0.), (1., 0.), (1., 1.), (0., 1.)]
LEFT_HALF = [(0., 0.), (.5, 0.), (.5, 1.), (0., 1.)]


def camera_state(*, parallel=True, position=(0, 0, 10), up=(0, 1, 0), size=(800, 800), dpr=1.,
                 viewport=(0., 0., 1., 1.)):
    renderer = vtk.vtkRenderer()
    window = vtk.vtkRenderWindow()
    window.SetSize(*size)
    window.AddRenderer(renderer)
    renderer.SetViewport(*viewport)
    camera = renderer.GetActiveCamera()
    camera.SetPosition(*position)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(*up)
    camera.SetParallelProjection(parallel)
    camera.SetParallelScale(4.)
    camera.SetViewAngle(90.)
    camera.SetClippingRange(1., 20.)
    clip = camera.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1., 1.)
    view = camera.GetModelViewTransformMatrix()
    return CameraProjection(
        np.asarray(clip.GetData()).reshape(4, 4), np.asarray(view.GetData()).reshape(4, 4), (1., 20.),
        'orthographic' if parallel else 'perspective', viewport, size, dpr,
    ), renderer, window


@pytest.mark.parametrize('parallel', [True, False])
def test_polygon_projection_matches_vtk_at_viewport_and_dpr(parallel):
    viewport = (.1, .2, .9, .95)
    camera, renderer, window = camera_state(parallel=parallel, size=(1200, 900), dpr=1.5, viewport=viewport)
    world = (1., 2., 4.)
    renderer.SetWorldPoint(*world, 1.)
    renderer.WorldToDisplay()
    x, y, _ = renderer.GetDisplayPoint()
    u, v = screen_to_uv(x, 900 - y, 1200, 900, viewport)
    assert screen_to_uv(x / 1.5, (900 - y) / 1.5, 800, 600, viewport) == pytest.approx((u, v))
    assert uv_to_screen(u, v, 1200, 900, viewport) == pytest.approx((x, 900 - y))
    eps = .005
    operation = PolygonOperation(
        'keep', [(u-eps, v-eps), (u+eps, v-eps), (u+eps, v+eps), (u-eps, v+eps)],
        camera, (5.9, 6.1),
    )
    assert operation.mask(np.array([world, (1., 2., 3.), (1., 1., 4.)])).tolist() == [True, False, False]
    replay = PolygonOperation.from_dict(json.loads(json.dumps(operation.to_dict())))
    assert replay.mask(np.asarray([world])).tolist() == [True]


def test_polygon_is_not_a_box_and_includes_edges():
    camera, _, _ = camera_state()
    triangle = PolygonOperation('keep', [(0., 0.), (1., 0.), (0., 1.)], camera, (8., 12.))
    # +Y is toward the top of the viewport. Last point is on the diagonal.
    xyz = np.array([[-3., 3., 0.], [3., -3., 0.], [2., 2., 0.]])
    assert triangle.mask(xyz).tolist() == [True, False, True]
    concave = PolygonOperation('keep', [(0., 0.), (1., 0.), (1., 1.), (.5, .5), (0., 1.)],
                               camera, (8., 12.))
    assert concave.mask(np.array([[0., 2., 0.], [0., -3., 0.]])).tolist() == [True, False]


@pytest.mark.parametrize('parallel', [True, False])
def test_depth_and_camera_frustum(parallel):
    camera, _, _ = camera_state(parallel=parallel)
    wide = PolygonOperation('keep', FULL_VIEW, camera, (0., 40.))
    xyz = np.array([[0., 0., 11.], [0., 0., 9.5], [0., 0., 5.],
                    [0., 0., 0.], [0., 0., -11.], [100., 0., 0.]])
    assert wide.mask(xyz).tolist() == [False, False, True, True, False, False]
    narrow = PolygonOperation('keep', FULL_VIEW, camera, (4., 6.))
    assert narrow.mask(xyz).tolist() == [False, False, True, False, False, False]


@pytest.mark.parametrize('vertices', [
    [(0., 0.), (1., 1.)],
    [(0., 0.), (.5, .5), (1., 1.)],
    [(0., 0.), (1., 0.), (0., 0.)],
    [(0., 0.), (1., 1.), (.1, 1.), (.8, 0.)],
])
def test_invalid_polygon(vertices):
    camera, _, _ = camera_state()
    with pytest.raises(CropError):
        PolygonOperation('keep', vertices, camera, (2., 3.))
    with pytest.raises(CropError, match='Depth'):
        PolygonOperation('keep', FULL_VIEW, camera, (3., 2.))


def sample_selection():
    front, _, _ = camera_state()
    side, _, _ = camera_state(position=(0, 10, 0), up=(0, 0, 1))
    base = axis_aligned_box(-2.1, 3.1, -3.1, 3.1, -1., 1.)
    return PolygonSelection(base, (
        PolygonOperation('keep', LEFT_HALF, front, (9.5, 10.5)),
        PolygonOperation('remove', FULL_VIEW, side, (9.5, 10.5)),
    ))


def sample_points():
    return np.array([(x, y, z) for x in range(-3, 4) for y in range(-2, 3) for z in (-1, 0, 1)])


def expected_points(xyz):
    x, y, z = xyz.T
    return (x >= -2) & (x <= 0) & (y != 0) & (z == 0)


@pytest.mark.parametrize(('input_ext', 'output_ext'), [('las', 'laz'), ('laz', 'las'), ('ply', 'ply')])
def test_polygon_export_full_resolution_replay_and_source(tmp_path, input_ext, output_ext):
    path = tmp_path / f'source.{input_ext}'
    xyz = sample_points()
    if input_ext == 'ply':
        records = np.zeros(len(xyz), dtype=[('x', 'f8'), ('y', 'f8'), ('z', 'f8'),
                                            ('f_dc_0', 'f4'), ('scale_0', 'f4'), ('opacity', 'f4')])
        records['x'], records['y'], records['z'] = xyz.T
        records['f_dc_0'] = np.linspace(-.5, .5, len(xyz))
        records['scale_0'] = np.linspace(-6, -4, len(xyz))
        records['opacity'] = .7
        PlyData([PlyElement.describe(records, 'vertex')]).write(path)
    else:
        las = laspy.create(point_format=3)
        las.header.scales = np.array([.001, .002, .005])
        las.header.offsets = np.array([10., -20., 30.])
        las.x, las.y, las.z = xyz.T
        rows = np.arange(len(xyz))
        las.intensity = rows * 21
        las.red, las.green, las.blue = rows * 421, rows * 321, rows * 221
        las.gps_time = rows + 123.5
        las.classification = rows % 7
        las.return_number, las.number_of_returns = 1 + rows % 3, np.full(len(xyz), 3)
        las.write(path)
        records = las.points.array
    doc = load_cloud(path)
    before = file_sha256(path)
    selection = sample_selection()
    mask = expected_points(xyz)
    np.testing.assert_array_equal(selection.mask(xyz), mask)
    preview, _ = doc.preview(4)
    assert selection.mask(preview).sum() < mask.sum()
    out, metadata, info = export_crop(doc, selection, tmp_path / f'crop.{output_ext}')
    if output_ext == 'ply':
        actual = PlyData.read(out)['vertex'].data
    else:
        saved = laspy.read(out)
        np.testing.assert_array_equal(saved.header.scales, las.header.scales)
        np.testing.assert_array_equal(saved.header.offsets, las.header.offsets)
        actual = saved.points.array
    assert actual.dtype == records.dtype and actual.tobytes() == records[mask].tobytes()
    assert info['input_sha256'] == before == file_sha256(path)
    assert info['roi_kind'] == 'Polygon' and info['retained_points'] == mask.sum()
    assert info['selection']['initial_box_kind'] == 'AABB'
    np.testing.assert_array_equal(load_selection_json(metadata, doc).mask(xyz), mask)
    info['input_sha256'] = '0' * 64
    metadata.write_text(json.dumps(info), encoding='utf-8')
    with pytest.raises(CropError, match='SHA-256'):
        load_selection_json(metadata, doc)


def test_polygon_ply_metadata_failure_leaves_no_partial_crop(tmp_path, monkeypatch):
    path = tmp_path / 'source.ply'
    xyz = sample_points()
    records = np.zeros(len(xyz), dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')])
    records['x'], records['y'], records['z'] = xyz.T
    PlyData([PlyElement.describe(records, 'vertex')]).write(path)
    doc = load_cloud(path)

    def fail_json(*args):
        raise OSError('test write failure')

    monkeypatch.setattr(core, 'write_json_atomic', fail_json)
    with pytest.raises(OSError, match='test write failure'):
        export_crop(doc, sample_selection(), tmp_path / 'crop.ply')
    assert list(tmp_path.iterdir()) == [path]
