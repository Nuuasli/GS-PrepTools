"""Chunked LAS/LAZ document and verified export for the desktop cropper."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import laspy
import numpy as np
from plyfile import PlyData
from pyproj.exceptions import CRSError

from .core import (
    CHUNK_SIZE, HISTORY_SCHEMA, LAS_SUFFIXES, PLY_TYPES, PREVIEW_LIMIT, BoxSelection, CropError,
    box_kind, check_cancel, file_sha256, publish_crop, write_json_atomic,
)
from .brush import BrushSelection
from .center import CenterSelection
from .polygon import PolygonSelection


AXES = ('X', 'Y', 'Z')
RGB = ('red', 'green', 'blue')
IO_ERRORS = (OSError, ValueError, OverflowError, laspy.LaspyException)


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _xyz(points) -> np.ndarray:
    return np.column_stack([points[axis.lower()] for axis in AXES])


def _records(header):
    return [record for records in (header.vlrs, header.evlrs) if records
            for record in records if record.user_id != 'laszip encoded']


@dataclass
class LasDocument:
    path: Path
    header: laspy.LasHeader
    source_stamp: tuple[int, int]
    spatial: dict
    rgb_status: str

    other_elements = ()
    is_gaussian = False

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.header.point_format.dimension_names)

    @property
    def count(self) -> int:
        return self.header.point_count

    @property
    def file_size(self) -> int:
        return self.source_stamp[0]

    @property
    def format_name(self) -> str:
        return 'LAZ' if self.header.are_points_compressed else 'LAS'

    @property
    def classification(self) -> str:
        return f'Point cloud {self.format_name} {self.header.version} / format {self.header.point_format.id}'

    @property
    def bounds(self) -> tuple:
        return tuple(np.column_stack((self.header.mins, self.header.maxs)).ravel())

    def check_source(self):
        if _stamp(self.path) != self.source_stamp:
            raise CropError('File LAS/LAZ berubah sejak dibuka. Buka ulang sebelum melanjutkan.')

    def chunks(self):
        self.check_source()
        count = 0
        with laspy.open(self.path) as reader:
            for points in reader.chunk_iterator(CHUNK_SIZE):
                if not len(points):
                    break
                count += len(points)
                yield points
        if count != self.count:
            raise CropError(f'LAS/LAZ terpotong: terbaca {count:,} dari {self.count:,} titik.')
        self.check_source()

    def preview(self, max_points: int = PREVIEW_LIMIT, progress=None):
        if max_points <= 0:
            raise CropError('Jumlah preview harus > 0.')
        size = min(max_points, self.count)
        indices = np.linspace(0, self.count - 1, size, dtype=np.int64)
        coords = np.empty((size, 3), dtype=np.float64)
        keys = (*RGB, 'intensity') if all(k in self.names for k in RGB) else ('intensity',)
        attrs = {name: np.empty(size, dtype=np.uint16) for name in keys}
        rgb_seen = False
        start, sample_start = 0, 0
        low = np.full(3, np.inf)
        high = np.full(3, -np.inf)
        try:
            for points in self.chunks():
                end = start + len(points)
                sample_end = indices.searchsorted(end)
                local = indices[sample_start:sample_end] - start
                for col, axis in enumerate(AXES):
                    raw = points[axis]
                    scale, offset = self.header.scales[col], self.header.offsets[col]
                    coords[sample_start:sample_end, col] = raw[local] * scale + offset
                    low[col] = min(low[col], raw.min() * scale + offset)
                    high[col] = max(high[col], raw.max() * scale + offset)
                for name in keys:
                    attrs[name][sample_start:sample_end] = points[name][local]
                if not rgb_seen and self.rgb_status != 'absent':
                    rgb_seen = any(np.any(points[name]) for name in RGB)
                start, sample_start = end, sample_end
                if progress:
                    progress(int(100 * start / self.count))
        except IO_ERRORS as exc:
            raise CropError(f'Gagal membaca titik LAS/LAZ: {exc}') from exc
        if not np.isfinite([low, high]).all():
            raise CropError('LAS/LAZ menghasilkan koordinat di luar rentang float64.')
        # Use the observed bounds for the box even if the source header is stale.
        self.header.mins, self.header.maxs = low, high
        if self.rgb_status != 'absent':
            self.rgb_status = 'available' if rgb_seen else 'all_zero'
        return coords, attrs

    def metadata(self) -> dict:
        return {
            'version': str(self.header.version),
            'point_format': self.header.point_format.id,
            'scales': self.header.scales.tolist(),
            'offsets': self.header.offsets.tolist(),
            'rgb': self.rgb_status,
            'dimensions': list(self.names),
            'global_encoding': self.header.global_encoding.value,
            'gps_time_type': (self.header.global_encoding.gps_time_type.name
                              if 'gps_time' in self.names else None),
            'spatial': self.spatial,
        }


def load_las(path: Path) -> LasDocument:
    try:
        stamp = _stamp(path)
        with laspy.open(path) as reader:
            header = reader.header
        if header.point_count <= 0:
            raise CropError('LAS/LAZ tidak berisi titik.')
        if not np.isfinite([header.scales, header.offsets]).all() or np.any(header.scales <= 0):
            raise CropError('Scale/offset LAS/LAZ tidak valid.')
        if header.point_format.id in (4, 5, 9, 10):
            raise CropError('LAS/LAZ dengan waveform belum didukung.')
        records = _records(header)
        if any(v.user_id.lower() == 'copc' for v in records):
            raise CropError('COPC LAZ menggunakan indeks khusus dan belum didukung.')
        spatial = {
            'projection_records': [
                {'user_id': v.user_id, 'record_id': v.record_id}
                for v in records if v.user_id == 'LASF_Projection'
            ],
            'crs_wkt': None,
            'axis_units': [],
        }
        try:
            crs = header.parse_crs()
            if crs is not None:
                spatial.update(crs_wkt=crs.to_wkt(), crs_name=crs.name,
                               axis_units=[axis.unit_name for axis in crs.axis_info])
        except (CRSError, UnicodeError, ValueError) as exc:
            spatial['crs_warning'] = str(exc)
        rgb = 'unchecked' if all(k in header.point_format.dimension_names for k in RGB) else 'absent'
        doc = LasDocument(path, header, stamp, spatial, rgb)
        doc.check_source()
        return doc
    except IO_ERRORS as exc:
        raise CropError(f'Gagal membuka LAS/LAZ: {exc}') from exc


def _selection_chunks(doc, roi, progress, first_step, last_step, cancelled):
    scanned = 0
    for points in doc.chunks():
        check_cancel(cancelled)
        xyz = _xyz(points)
        mask = roi.mask(xyz)
        if mask.any():
            yield points[mask], xyz[mask]
        scanned += len(points)
        if progress:
            progress(first_step + (last_step - first_step) * scanned // doc.count)


def _write_selected(chunks, write, encode):
    digest = sha256()
    low, high, count = np.full(3, np.inf), np.full(3, -np.inf), 0
    for points, xyz in chunks:
        records = encode(points, xyz)
        digest.update(records.tobytes())
        write(points, records)
        low = np.minimum(low, xyz.min(axis=0))
        high = np.maximum(high, xyz.max(axis=0))
        count += len(points)
    if count == 0:
        raise CropError('Kotak tidak mengandung titik. Crop kosong tidak diekspor.')
    return count, low, high, digest.digest()


def _record_signature(header):
    return [(v.user_id, v.record_id, v.description, v.record_data_bytes()) for v in _records(header)]


def _verify_native(path, source_header, written_header, expected, progress, cancelled):
    count, low, high, digest = expected
    with laspy.open(path) as reader:
        header = reader.header
        checks = {
            'point count': header.point_count == count,
            'version': header.version == source_header.version,
            'point format': header.point_format == source_header.point_format,
            'compression': header.are_points_compressed == (path.suffix == '.laz'),
            'scale': np.array_equal(header.scales, source_header.scales),
            'offset': np.array_equal(header.offsets, source_header.offsets),
            'minimum XYZ': np.array_equal(header.mins, low),
            'maximum XYZ': np.array_equal(header.maxs, high),
            'global encoding': header.global_encoding.value == source_header.global_encoding.value,
            'VLR/EVLR': _record_signature(header) == _record_signature(written_header),
            'return counts': np.array_equal(header.number_of_points_by_return,
                                            written_header.number_of_points_by_return),
        }
        mismatches = [field for field, valid in checks.items() if not valid]
        if mismatches:
            raise CropError('Verifikasi header LAS/LAZ gagal: ' + ', '.join(mismatches))
        readback = sha256()
        actual_count = 0
        for points in reader.chunk_iterator(CHUNK_SIZE):
            check_cancel(cancelled)
            readback.update(points.array.tobytes())
            actual_count += len(points)
            if progress:
                progress(80 + 19 * actual_count // count)
        if actual_count != count or readback.digest() != digest:
            raise CropError('Verifikasi record titik LAS/LAZ gagal.')


def _export_native(doc, roi, path, progress, cancelled):
    with laspy.open(path, mode='w', header=doc.header,
                    do_compress=(path.suffix == '.laz')) as writer:
        result = _write_selected(
            _selection_chunks(doc, roi, progress, 0, 80, cancelled),
            lambda points, _: writer.write_points(points),
            lambda points, _: points.array,
        )
        if doc.header.evlrs:
            writer.write_evlrs(doc.header.evlrs)
    # laspy recomputes the Extra Bytes VLR extrema as the selected records are written.
    _verify_native(path, doc.header, writer.header, result, progress, cancelled)
    return result, list(doc.names)


def _ply_dtype(doc):
    sample = laspy.ScaleAwarePointRecord.zeros(1, header=doc.header)
    fields = [(name, '<f8') for name in ('x', 'y', 'z')]
    extras = set(doc.header.point_format.extra_dimension_names)
    for name in doc.names:
        if name in AXES:
            continue
        # Preserve encoded extra bytes. Their scale/offset are described in JSON.
        values = sample.array[name] if name in extras else np.asarray(sample[name])
        dtype = values.dtype
        if (name in ('x', 'y', 'z') or not name.isascii() or any(c.isspace() for c in name)
                or values.ndim != 1 or (dtype.kind, dtype.itemsize) not in PLY_TYPES):
            raise CropError(f'Atribut {name!r} tidak kompatibel dengan PLY scalar. Pilih LAS/LAZ.')
        fields.append((name, dtype.newbyteorder('<')))
    return np.dtype(fields), extras


def _export_ply(doc, roi, path, progress, cancelled):
    dtype, extras = _ply_dtype(doc)
    count = sum(len(points) for points, _ in _selection_chunks(doc, roi, progress, 0, 30, cancelled))
    if not count:
        raise CropError('Kotak tidak mengandung titik. Crop kosong tidak diekspor.')

    def encode(points, xyz):
        records = np.empty(len(points), dtype=dtype)
        for col, name in enumerate(('x', 'y', 'z')):
            records[name] = xyz[:, col]
        for name in dtype.names[3:]:
            records[name] = points.array[name] if name in extras else points[name]
        return records

    with path.open('wb') as output:
        header = ['ply', 'format binary_little_endian 1.0',
                  'comment Derived LAS point cloud; see selection JSON for LAS metadata.',
                  f'element vertex {count}']
        for name in dtype.names:
            datatype = dtype[name]
            header.append(f'property {PLY_TYPES[(datatype.kind, datatype.itemsize)]} {name}')
        output.write(('\n'.join(header + ['end_header', ''])).encode('ascii'))
        result = _write_selected(
            _selection_chunks(doc, roi, progress, 30, 80, cancelled),
            lambda _, records: output.write(records.tobytes()), encode,
        )
    saved = PlyData.read(str(path), mmap='r')['vertex'].data
    try:
        readback = sha256()
        for start in range(0, len(saved), CHUNK_SIZE):
            check_cancel(cancelled)
            readback.update(saved[start:start + CHUNK_SIZE].tobytes())
            if progress:
                progress(80 + 19 * min(start + CHUNK_SIZE, len(saved)) // len(saved))
        if len(saved) != count or result[0] != count or saved.dtype != dtype or readback.digest() != result[3]:
            raise CropError('Verifikasi ulang PLY turunan gagal.')
    finally:
        del saved  # Windows requires the memory mapping to close before the rename.
    return result, list(dtype.names)


def export_las_crop(doc: LasDocument, roi: BoxSelection | PolygonSelection | BrushSelection | CenterSelection, output, *,
                    overwrite=False, progress=None, selection_history=None, cancelled=None):
    out = Path(output).expanduser().resolve()
    suffix = out.suffix.lower()
    if suffix not in (*LAS_SUFFIXES, '.ply'):
        raise CropError('Pilih ekstensi output .las, .laz, atau .ply.')
    if out == doc.path or (out.exists() and out.samefile(doc.path)):
        raise CropError('File asli tidak boleh ditimpa.')
    meta = out.with_name(out.stem + '_selection.json')
    if not out.parent.is_dir():
        raise CropError('Folder output belum ada.')
    if not overwrite and (out.exists() or meta.exists()):
        raise CropError('File output/metadata sudah ada. Pilih nama lain atau setujui overwrite.')

    try:
        doc.check_source()
        source_hash = file_sha256(doc.path, cancelled=cancelled)
        with tempfile.TemporaryDirectory(prefix='.crop-', dir=out.parent) as work:
            staged = Path(work) / ('selected' + suffix)
            writer = _export_ply if suffix == '.ply' else _export_native
            result, properties = writer(doc, roi, staged, progress, cancelled)
            count, low, high, _ = result
            is_polygon = isinstance(roi, PolygonSelection)
            is_brush = isinstance(roi, BrushSelection)
            roi_kind = roi.shape if isinstance(roi, CenterSelection) else (
                'Brush' if is_brush else ('Polygon' if is_polygon else box_kind(roi))
            )
            payload = {
                'schema_version': HISTORY_SCHEMA if is_brush else (3 if is_polygon else 2),
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'input_file': str(doc.path), 'input_size_bytes': doc.file_size,
                'input_modified_ns': doc.source_stamp[1], 'input_sha256': source_hash,
                'input_format': doc.format_name, 'input_classification': doc.classification,
                'output_file': str(out), 'output_format': suffix[1:].upper(),
                'source_points': doc.count, 'retained_points': count,
                'retained_percent': round(100 * count / doc.count, 5),
                'selected_bounds_xyz': np.column_stack((low, high)).ravel().tolist(),
                'roi_kind': roi_kind,
                'selection': roi.to_dict(), 'tolerance': 1e-7, 'las_source': doc.metadata(),
                'preserved_vertex_properties': properties,
                'coordinate_transform': 'none', 'smoothing': 'none', 'denoising': 'none',
                'verification': 'Reopened output and verified count and all point-record bytes.',
            }
            if selection_history is not None:
                payload.update(schema_version=HISTORY_SCHEMA, selection_history=selection_history)
            if suffix == '.ply':
                payload['derivative'] = {
                    'xyz': 'float64, decoded with source LAS scale and offset',
                    'native_header_records_in_output': False,
                    'extra_dimensions': [
                        {'name': dim.name, 'scales': None if dim.scales is None else dim.scales.tolist(),
                         'offsets': None if dim.offsets is None else dim.offsets.tolist()}
                        for dim in doc.header.point_format.extra_dimensions
                    ],
                }
            staged_meta = Path(work) / 'selection.json'
            write_json_atomic(staged_meta, payload)
            doc.check_source()
            check_cancel(cancelled)
            publish_crop(staged, staged_meta, out, meta, overwrite)
        if progress:
            progress(100)
        return out, meta, payload
    except IO_ERRORS as exc:
        raise CropError(f'Gagal mengekspor crop LAS/LAZ: {exc}') from exc
