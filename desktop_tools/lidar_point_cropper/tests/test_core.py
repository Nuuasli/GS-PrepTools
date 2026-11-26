"""Headless regression tests for cropping, PLY integrity, and ROI replay."""
import json
from pathlib import Path

import numpy as np
import pytest

from lidar_cropper.core import (
    BoxSelection, CropError, axis_aligned_box, box_corners, load_cloud,
    export_crop, load_selection_json,
)


def test_aabb_exact_membership_and_offset():
    roi = axis_aligned_box(100, 102, -45, -43, 4, 7)
    points = np.array([[100, -45, 4], [101, -44, 6], [102, -43, 7],
                       [101, -42, 6], [99, -44, 6]])
    assert roi.mask(points).tolist() == [True, True, True, False, False]
    assert len(box_corners(roi)) == 8
    replay = BoxSelection.from_dict(roi.to_dict())
    assert replay.mask(points).tolist() == roi.mask(points).tolist()


def test_oriented_box_is_not_axis_aligned():
    angle = np.pi / 4
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0.],
                         [np.sin(angle), np.cos(angle), 0.], [0., 0., 1.]])
    center = np.array([102., -45., 31.])
    half = [2., .3, 1.]
    origins = []
    normals = []
    for axis, extent in enumerate(half):
        vec = rotation[:, axis]
        origins.extend([center - extent*vec, center + extent*vec])
        normals.extend([-vec, vec])
    # Reverse some normals to imitate VTK widget orientation changes.
    normals[2] = -normals[2]
    roi = BoxSelection.from_planes(origins, normals)
    local = np.array([[1.0, 0., 0.], [0., 0.2, 0.], [0, 0.4, 0],
                      [2.1, 0., 0.]])
    xyz = center + local @ rotation.T
    assert roi.mask(xyz).tolist() == [True, True, False, False]
    assert len(box_corners(roi)) == 8


def test_invalid_roi():
    with pytest.raises(CropError):
        BoxSelection.from_planes(np.zeros((3, 3)), np.zeros((3, 3)))
    with pytest.raises(CropError):
        axis_aligned_box(2, 1, 0, 1, 0, 1)


# The PLY tests require `pip install -r requirements.txt`. They are skipped in
# environments without `plyfile` (e.g. source-only review in a sandbox).
try:
    from plyfile import PlyData, PlyElement
except ImportError:
    PlyData = PlyElement = None

needs_ply = pytest.mark.skipif(PlyData is None, reason='Install plyfile to run PLY I/O tests')


def make_ply(path, *, ascii=False, mesh=False, gaussian=False):
    dtype = [('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
             ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'),
             ('intensity', 'f4'), ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4')]
    if gaussian:
        dtype += [('f_dc_0', 'f4'), ('scale_0', 'f4'), ('opacity', 'f4')]
    v = np.zeros(6, dtype=dtype)
    v['x'] = [0, 0.2, .8, 1.2, 2., 3.]
    v['y'] = [.2, .5, .9, 1., 2., 3.]
    v['z'] = [.2, .5, .9, 1., 2., 3.]
    v['red'] = [5, 9, 80, 120, 240, 255]
    v['green'] = [11, 12, 13, 14, 15, 16]
    v['intensity'] = [1, 2, 3, 4, 5, 6]
    v['nx'] = np.arange(6) * .1
    if gaussian:
        v['scale_0'] = .2
    elements = [PlyElement.describe(v, 'vertex')]
    if mesh:
        faces = np.array([([0, 1, 2],)], dtype=[('vertex_indices', object)])
        elements.append(PlyElement.describe(faces, 'face'))
    PlyData(elements, text=ascii, byte_order='<', comments=['source: sample']).write(str(path))
    return v


@needs_ply
@pytest.mark.parametrize('ascii', [False, True])
def test_ply_export_preserves_all_vertex_attributes_and_input(tmp_path, ascii):
    source = tmp_path / ('source_ascii.ply' if ascii else 'source_bin.ply')
    original_data = make_ply(source, ascii=ascii)
    source_bytes = source.read_bytes()
    doc = load_cloud(source)
    assert doc.count == 6
    assert doc.classification == 'Point cloud PLY'
    xyz, attrs = doc.preview(max_points=4)
    assert xyz.shape == (4, 3)
    assert 'intensity' in attrs
    roi = axis_aligned_box(-.1, 1., -.1, 1., -.1, 1.)
    out, metadata, result = export_crop(doc, roi, tmp_path / 'cropped.ply')
    ply = PlyData.read(str(out))
    assert not ply.text
    assert len(ply['vertex'].data) == 3
    assert tuple(ply['vertex'].data.dtype.names) == tuple(original_data.dtype.names)
    for key in original_data.dtype.names:
        np.testing.assert_array_equal(ply['vertex'].data[key], original_data[key][:3])
    assert source.read_bytes() == source_bytes
    assert result['source_points'] == 6
    assert result['retained_points'] == 3
    assert Path(result['output_file']) == out
    assert json.loads(metadata.read_text('utf-8'))['coordinate_transform'] == 'none'
    recovered = load_selection_json(metadata, doc)
    np.testing.assert_array_equal(recovered.mask(xyz), roi.mask(xyz))
    with pytest.raises(CropError, match='sudah ada'):
        export_crop(doc, roi, out)


@needs_ply
def test_reject_mesh_without_explicit_confirmation(tmp_path):
    source = tmp_path / 'mesh.ply'
    make_ply(source, mesh=True)
    doc = load_cloud(source)
    assert 'face' in doc.other_elements
    roi = axis_aligned_box(-1, 1, -1, 1, -1, 1)
    with pytest.raises(CropError, match='element non-vertex'):
        export_crop(doc, roi, tmp_path / 'x.ply')
    out, meta, result = export_crop(doc, roi, tmp_path / 'x.ply', allow_drop_elements=True)
    assert [e.name for e in PlyData.read(str(out)).elements] == ['vertex']
    assert result['excluded_nonvertex_elements'] == ['face']


@needs_ply
def test_gaussian_warning_classification_and_empty_crop(tmp_path):
    source = tmp_path / 'gaussian.ply'
    make_ply(source, gaussian=True)
    doc = load_cloud(source)
    assert doc.is_gaussian
    roi = axis_aligned_box(500, 510, 500, 510, 500, 510)
    with pytest.raises(CropError, match='kosong'):
        export_crop(doc, roi, tmp_path / 'not_written.ply')
    assert not (tmp_path / 'not_written.ply').exists()


@needs_ply
def test_replay_rejects_different_source(tmp_path):
    source = tmp_path / 'original.ply'
    make_ply(source)
    doc = load_cloud(source)
    roi = axis_aligned_box(-1, 1, -1, 1, -1, 1)
    _, meta, _ = export_crop(doc, roi, tmp_path / 'selected.ply')
    fake = json.loads(meta.read_text('utf-8'))
    fake['input_size_bytes'] += 1
    meta.write_text(json.dumps(fake), encoding='utf8')
    with pytest.raises(CropError, match='berbeda'):
        load_selection_json(meta, doc)


@needs_ply
def test_big_endian_integer_cloud_exports_points_omitted_from_preview(tmp_path):
    source = tmp_path / 'integer_coordinates.ply'
    vertices = np.zeros(5, dtype=[('x', '>i4'), ('y', '>i2'), ('z', '>u4'),
                                  ('intensity', '>f8'), ('red', 'u1')])
    vertices['x'] = [0, 1, 2, 3, 4]
    vertices['intensity'] = [0., .25, .5, .75, 1.]
    vertices['red'] = [10, 20, 30, 40, 50]
    PlyData([PlyElement.describe(vertices, 'vertex')], byte_order='>').write(str(source))
    original = source.read_bytes()

    doc = load_cloud(source)
    roi = axis_aligned_box(0, 4, -1, 1, -1, 1)
    coords, _ = doc.preview(max_points=2)
    assert roi.mask(coords).sum() == 2
    output, metadata, summary = export_crop(doc, roi, tmp_path / 'full_crop.ply')

    cropped = PlyData.read(str(output))
    assert cropped.byte_order == '<'
    assert summary['retained_points'] == len(vertices)
    assert cropped['vertex'].data.tobytes() == vertices.astype(vertices.dtype.newbyteorder('<')).tobytes()
    assert source.read_bytes() == original
    assert load_selection_json(metadata, doc).mask(coords).all()


def test_streaming_binary_writer_without_gui_or_plyfile(tmp_path):
    """Verify actual streaming writer and metadata independent of plyfile install."""
    from types import SimpleNamespace
    from lidar_cropper.core import CloudDocument
    source = tmp_path / 'source.ply'
    source.write_bytes(b'synthetic source placeholder')
    rows = np.zeros(10, dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
                               ('red', 'u1'), ('intensity', 'f8')])
    rows['x'] = np.arange(10, dtype='f4')
    rows['y'] = -3.125
    rows['z'] = 17.5
    rows['red'] = np.arange(10) * 10
    rows['intensity'] = np.arange(10) * 0.22
    fakeply = SimpleNamespace(text=True, comments=['a test'], obj_info=[])
    doc = CloudDocument(source, fakeply, rows,
                        (0, 9, -3.125, -3.125, 17.5, 17.5),
                        rows.dtype.names, (), False)
    roi = axis_aligned_box(2, 7, -4, -3, 17, 18)
    out, meta, record = export_crop(doc, roi, tmp_path / 'cropped.ply')
    with open(out, 'rb') as fp:
        header = []
        while True:
            ln = fp.readline().decode('ascii')
            header.append(ln)
            if ln == 'end_header\n':
                break
        assert 'element vertex 6\n' in header
        assert 'property double intensity\n' in header
        received = np.frombuffer(fp.read(), dtype=rows.dtype)
    np.testing.assert_array_equal(received, rows[2:8])
    assert record['retained_points'] == 6
    replay = load_selection_json(meta, doc)
    np.testing.assert_array_equal(replay.mask(np.column_stack([rows[k] for k in ('x','y','z')])),
                                  roi.mask(np.column_stack([rows[k] for k in ('x','y','z')])))
