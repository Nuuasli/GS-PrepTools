import json
from pathlib import Path

import laspy
import numpy as np
import pytest
from plyfile import PlyData
from pyproj import CRS

from lidar_cropper import core, las
from lidar_cropper.core import CropError, axis_aligned_box, export_crop, file_sha256, load_cloud, load_selection_json


def sample_las(path, *, point_format=3, nonzero_rgb=True, extra_type='i2'):
    source = laspy.create(point_format=point_format, file_version='1.2')
    source.header.scales = np.array([.001, .002, .005])
    source.header.offsets = np.array([500_000., 9_000_000., 20.])
    source.header.add_crs(CRS.from_epsg(32750))
    source.add_extra_dim(laspy.ExtraBytesParams(name='confidence', type=extra_type))
    rows = np.arange(21)
    source.X = rows * 150
    source.Y = rows * 20
    source.Z = rows * 10
    source.intensity = rows + 40
    source.classification = rows % 7
    source.return_number = rows % 3 + 1
    source.number_of_returns = np.full(len(rows), 3)
    source.gps_time = rows * .125 + 18_000.75
    source.confidence = rows * 3 + 2
    if point_format == 3 and nonzero_rgb:
        source.red = rows * 3000
        source.green = np.full(len(rows), 65535)
        source.blue = rows * 850
    source.write(path)
    roi = axis_aligned_box(500_000.5, 500_002.0, 8_999_999., 9_000_005., 19., 22.)
    return source, roi


@pytest.mark.parametrize(('input_suffix', 'output_suffix'), [('las', 'laz'), ('laz', 'las')])
def test_native_roundtrip_preserves_records_header_and_replay(tmp_path, monkeypatch, input_suffix, output_suffix):
    monkeypatch.setattr(las, 'CHUNK_SIZE', 7)
    path = tmp_path / f'source.{input_suffix}'
    expected, roi = sample_las(path)
    expected = expected.points[(expected.X >= 500) & (expected.X <= 2000)]
    source_hash = file_sha256(path)
    doc = load_cloud(path)
    preview, attrs = doc.preview(max_points=4)
    assert len(preview) == 4
    assert attrs['red'].dtype == np.uint16
    assert doc.rgb_status == 'available'
    assert doc.spatial['crs_name'] == 'WGS 84 / UTM zone 50S'
    assert {'intensity', 'classification', 'gps_time'}.issubset(doc.names)

    output, metadata, info = export_crop(doc, roi, tmp_path / f'crop.{output_suffix}')
    saved = laspy.read(output)
    assert saved.header.point_count == len(expected) > roi.mask(preview).sum()
    assert saved.header.are_points_compressed == (output_suffix == 'laz')
    assert saved.points.array.tobytes() == expected.array.tobytes()
    assert saved.header.point_format == doc.header.point_format
    np.testing.assert_array_equal(saved.header.scales, doc.header.scales)
    np.testing.assert_array_equal(saved.header.offsets, doc.header.offsets)
    np.testing.assert_array_equal(saved.header.mins, saved.xyz.min(axis=0))
    np.testing.assert_array_equal(saved.header.maxs, saved.xyz.max(axis=0))
    assert saved.header.parse_crs() == doc.header.parse_crs()
    assert info['roi_kind'] == 'AABB'
    assert info['input_sha256'] == file_sha256(path) == source_hash
    np.testing.assert_array_equal(load_selection_json(metadata, load_cloud(path)).mask(preview),
                                  roi.mask(preview))


@pytest.mark.parametrize(('format_id', 'has_rgb', 'status'), [
    (1, False, 'absent'), (3, False, 'all_zero'), (3, True, 'available'),
])
def test_preview_rgb_status_scans_outside_sample(tmp_path, format_id, has_rgb, status):
    path = tmp_path / 'source.las'
    source, _ = sample_las(path, point_format=format_id, nonzero_rgb=False)
    if has_rgb:
        source.red[1] = 32768
        source.write(path)
    doc = load_cloud(path)
    _, attrs = doc.preview(max_points=2)
    assert doc.rgb_status == status
    assert not attrs.get('red', np.zeros(2)).any()


def test_derived_ply_preserves_compatible_types_and_values(tmp_path):
    path = tmp_path / 'source.las'
    source, roi = sample_las(path)
    doc = load_cloud(path)
    output, metadata, _ = export_crop(doc, roi, tmp_path / 'derivative.ply')
    vertices = PlyData.read(output)['vertex'].data
    selected = (source.X >= 500) & (source.X <= 2000)
    assert vertices.dtype['x'] == np.dtype('<f8')
    assert vertices.dtype['red'] == np.dtype('<u2')
    for key in ('x', 'y', 'z', 'red', 'green', 'blue', 'intensity', 'gps_time',
                'classification', 'return_number', 'confidence'):
        np.testing.assert_array_equal(vertices[key], np.asarray(source[key])[selected])
    assert json.loads(metadata.read_text('utf-8'))['derivative']['native_header_records_in_output'] is False


def test_unsupported_ply_field_reports_and_retains_native_support(tmp_path):
    path = tmp_path / 'source.las'
    source, roi = sample_las(path, extra_type='u8')
    doc = load_cloud(path)
    with pytest.raises(CropError, match='confidence'):
        export_crop(doc, roi, tmp_path / 'bad.ply')
    assert not (tmp_path / 'bad.ply').exists()
    out, _, _ = export_crop(doc, roi, tmp_path / 'good.las')
    assert laspy.read(out).points.array.dtype['confidence'] == source.points.array.dtype['confidence']


def test_replay_rejects_same_name_and_size_with_changed_bytes(tmp_path):
    path = tmp_path / 'source.las'
    _, roi = sample_las(path)
    doc = load_cloud(path)
    _, metadata, _ = export_crop(doc, roi, tmp_path / 'crop.las')
    with path.open('r+b') as source:
        source.seek(-1, 2)
        value = source.read(1)
        source.seek(-1, 2)
        source.write(bytes([value[0] ^ 1]))
    with pytest.raises(CropError, match='SHA-256'):
        load_selection_json(metadata, load_cloud(path))


def test_failed_publish_rolls_back_output(tmp_path, monkeypatch):
    path = tmp_path / 'source.las'
    _, roi = sample_las(path)
    doc = load_cloud(path)
    out = tmp_path / 'crop.las'
    out.write_bytes(b'old crop')
    meta = tmp_path / 'crop_selection.json'
    meta.write_text('old metadata')
    replace = core.os.replace

    def fail_final_metadata(src, dst):
        if Path(dst) == meta:
            raise PermissionError('synthetic rename failure')
        return replace(src, dst)

    monkeypatch.setattr(core.os, 'replace', fail_final_metadata)
    with pytest.raises(CropError, match='synthetic rename failure'):
        export_crop(doc, roi, out, overwrite=True)
    assert out.read_bytes() == b'old crop'
    assert meta.read_text() == 'old metadata'
    assert not list(tmp_path.glob('.crop-*'))


def test_empty_crop_and_source_overwrite_leave_no_new_output(tmp_path):
    path = tmp_path / 'source.las'
    _, roi = sample_las(path)
    doc = load_cloud(path)
    source_hash = file_sha256(path)
    with pytest.raises(CropError, match='asli'):
        export_crop(doc, roi, path, overwrite=True)
    empty = axis_aligned_box(1, 2, 1, 2, 1, 2)
    with pytest.raises(CropError, match='kosong'):
        export_crop(doc, empty, tmp_path / 'empty.laz')
    assert list(tmp_path.iterdir()) == [path]
    assert file_sha256(path) == source_hash


def test_native_las_14_keeps_spatial_evlr(tmp_path):
    path = tmp_path / 'source.las'
    cloud = laspy.create(point_format=6, file_version='1.4')
    spatial = laspy.vlrs.known.WktCoordinateSystemVlr(CRS.from_epsg(4326).to_wkt())
    cloud.evlrs = laspy.vlrs.vlrlist.VLRList([spatial])
    cloud.header.global_encoding.wkt = True
    cloud.X = [100, 200, 300]
    cloud.Y = [200, 200, 200]
    cloud.Z = [300, 300, 300]
    cloud.write(path)
    doc = load_cloud(path)
    assert doc.spatial['crs_name'] == 'WGS 84'
    roi = axis_aligned_box(.5, 2.5, 0, 4, 0, 4)
    output, _, _ = export_crop(doc, roi, tmp_path / 'crop.laz')
    actual = laspy.read(output)
    assert len(actual.points) == 2
    assert actual.evlrs[0].record_data_bytes() == spatial.record_data_bytes()
    assert actual.header.parse_crs() == CRS.from_epsg(4326)


def test_truncated_las_rejects_preview_and_export(tmp_path):
    path = tmp_path / 'truncated.las'
    _, roi = sample_las(path)
    with path.open('r+b') as source:
        source.truncate(path.stat().st_size - 9)
    doc = load_cloud(path)
    with pytest.raises(CropError, match='LAS/LAZ'):
        doc.preview()
    out = tmp_path / 'crop.las'
    with pytest.raises(CropError, match='LAS/LAZ'):
        export_crop(doc, roi, out)
    assert not out.exists()
