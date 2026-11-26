"""Geometry & PLY I/O. No GUI, no coordinate transformations, no denoising."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
from pathlib import Path
from typing import Callable

import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plyfile import PlyData
    from .center import CenterSelection
    from .las import LasDocument
    from .polygon import PolygonSelection
    from .brush import BrushSelection

LAS_SUFFIXES = ('.las', '.laz')
HISTORY_SCHEMA = 5

CHUNK_SIZE = 180_000
PREVIEW_LIMIT = 250_000
PLY_TYPES = {
    ('i', 1): 'char', ('u', 1): 'uchar',
    ('i', 2): 'short', ('u', 2): 'ushort',
    ('i', 4): 'int', ('u', 4): 'uint',
    ('f', 4): 'float', ('f', 8): 'double',
}


class CropError(RuntimeError):
    """User-facing validation or I/O failure."""


class CropCancelled(CropError):
    """An export was interrupted before its output was published."""


def check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise CropCancelled('Ekspor dibatalkan.')


@dataclass(frozen=True)
class BoxSelection:
    """Six plane origins + outward normals. Inside iff all distances <= tol."""
    origins: np.ndarray
    normals: np.ndarray

    @classmethod
    def from_planes(cls, origins, normals) -> 'BoxSelection':
        origins = np.asarray(origins, dtype=np.float64).copy()
        normals = np.asarray(normals, dtype=np.float64).copy()
        if origins.shape != (6, 3) or normals.shape != (6, 3):
            raise CropError('Kotak harus mempunyai tepat enam bidang XYZ.')
        if not np.isfinite(origins).all() or not np.isfinite(normals).all():
            raise CropError('Bidang seleksi tidak valid (NaN/inf).')
        magnitudes = np.linalg.norm(normals, axis=1)
        if np.any(magnitudes <= 1e-12):
            raise CropError('Normal bidang seleksi tidak valid.')
        normals /= magnitudes[:, None]
        # Find the true geometric box center by intersecting the three
        # midplanes of opposing face pairs. Averaging six arbitrary face
        # points is NOT generally the center (especially away from origin).
        remaining = list(range(6))
        basis, targets = [], []
        while remaining:
            i = remaining.pop(0)
            opposite = max(remaining, key=lambda j: abs(np.dot(normals[i], normals[j])))
            if abs(np.dot(normals[i], normals[opposite])) < 0.99:
                raise CropError('ROI tidak memiliki tiga pasang bidang sejajar.')
            remaining.remove(opposite)
            basis.append(normals[i])
            targets.append(0.5 * (np.dot(normals[i], origins[i]) +
                                  np.dot(normals[i], origins[opposite])))
        try:
            center = np.linalg.solve(np.array(basis), np.array(targets))
        except np.linalg.LinAlgError as exc:
            raise CropError('Bidang ROI tidak membentuk kotak 3D.') from exc
        # vtkBoxWidget normals can be inward/outward. Normalize direction.
        flip = np.einsum('ij,ij->i', center - origins, normals) > 0
        normals[flip] *= -1
        return cls(origins, normals)

    def mask(self, xyz: np.ndarray, tolerance: float = 1e-7) -> np.ndarray:
        xyz = np.asarray(xyz, dtype=np.float64)
        if xyz.ndim != 2 or xyz.shape[1] != 3:
            raise CropError('XYZ harus memiliki bentuk (N, 3).')
        # N x 6, with no point-by-point Python loop. Works for rotated boxes.
        offsets = np.einsum('ij,ij->i', self.origins, self.normals)
        distances = xyz @ self.normals.T - offsets
        return np.all(distances <= tolerance, axis=1)

    def to_dict(self):
        return {'type': 'oriented_bounding_box', 'origins': self.origins.tolist(),
                'normals_outward': self.normals.tolist(),
                'inside_rule': 'all dot(point-origin, normal) <= tolerance'}

    @classmethod
    def from_dict(cls, data):
        if data.get('type') != 'oriented_bounding_box':
            raise CropError('Metadata ROI bukan bounding box yang didukung.')
        return cls.from_planes(data['origins'], data['normals_outward'])


def axis_aligned_box(xmin, xmax, ymin, ymax, zmin, zmax) -> BoxSelection:
    if not (xmin < xmax and ymin < ymax and zmin < zmax):
        raise CropError('Batas bounding box harus memiliki volume positif.')
    origins = np.array([[xmin, 0, 0], [xmax, 0, 0], [0, ymin, 0],
                        [0, ymax, 0], [0, 0, zmin], [0, 0, zmax]], dtype='f8')
    normals = np.array([[-1, 0, 0], [1, 0, 0], [0, -1, 0],
                        [0, 1, 0], [0, 0, -1], [0, 0, 1]], dtype='f8')
    return BoxSelection.from_planes(origins, normals)


def box_kind(box: BoxSelection) -> str:
    return 'AABB' if np.allclose(np.max(np.abs(box.normals), axis=1), 1., atol=1e-12, rtol=0.) else 'OBB'


def box_corners(sel: BoxSelection) -> np.ndarray:
    """Recover corners for displaying a loaded ROI as a static wireframe."""
    b = np.einsum('ij,ij->i', sel.origins, sel.normals)
    candidates = []
    for ids in combinations(range(6), 3):
        a = sel.normals[list(ids)]
        if abs(np.linalg.det(a)) < 1e-9:
            continue
        p = np.linalg.solve(a, b[list(ids)])
        if np.all(sel.mask(p.reshape(1, 3), tolerance=1e-6)):
            if not any(np.linalg.norm(p - q) < 1e-5 for q in candidates):
                candidates.append(p)
    if len(candidates) != 8:
        raise CropError('Metadata ROI tidak membentuk sebuah kotak 3D yang valid.')
    return np.asarray(candidates)


def _xyz_chunk(records: np.ndarray) -> np.ndarray:
    return np.column_stack((records['x'], records['y'], records['z']))


@dataclass
class CloudDocument:
    path: Path
    ply: PlyData
    vertices: np.ndarray
    bounds: tuple[float, float, float, float, float, float]
    names: tuple[str, ...]
    other_elements: tuple[str, ...]
    is_gaussian: bool

    @property
    def count(self) -> int:
        return len(self.vertices)

    @property
    def file_size(self) -> int:
        return self.path.stat().st_size

    @property
    def classification(self) -> str:
        if self.is_gaussian:
            return 'Gaussian PLY (bukan LiDAR ground truth)'
        if 'face' in self.other_elements:
            return 'Mesh PLY (ekspor vertex-only)'
        return 'Point cloud PLY'

    def preview(self, max_points: int = PREVIEW_LIMIT):
        if max_points <= 0:
            raise CropError('Jumlah preview harus > 0.')
        indices = np.linspace(0, self.count - 1,
                              min(self.count, max_points), dtype=np.int64)
        xyz = np.empty((len(indices), 3), dtype=np.float64)
        for column, field in enumerate(('x', 'y', 'z')):
            xyz[:, column] = self.vertices[field][indices]
        attrs: dict[str, np.ndarray] = {}
        for key in ('red', 'green', 'blue', 'intensity'):
            if key in self.names:
                attrs[key] = np.asarray(self.vertices[key][indices])
        return xyz, attrs


def load_cloud(source: str | Path, progress: Callable[[int], None] | None = None) -> CloudDocument | LasDocument:
    path = Path(source).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in ('.ply', *LAS_SUFFIXES):
        raise CropError('Pilih file .ply, .las, atau .laz yang ada dan dapat dibaca.')
    if path.suffix.lower() in LAS_SUFFIXES:
        from .las import load_las
        return load_las(path)
    try:
        from plyfile import PlyData
        ply = PlyData.read(str(path), mmap='r')
        if 'vertex' not in [e.name for e in ply.elements]:
            raise CropError('PLY tidak memiliki element vertex.')
        vertices = ply['vertex'].data
        names = tuple(vertices.dtype.names or ())
        if not {'x', 'y', 'z'}.issubset(names):
            raise CropError('PLY harus memiliki vertex properties x, y, z.')
        if len(vertices) == 0:
            raise CropError('PLY tidak berisi titik.')
        for n in names:
            dtype = vertices.dtype.fields[n][0]
            if (dtype.kind, dtype.itemsize) not in PLY_TYPES or dtype.subdtype:
                raise CropError(f'Property vertex {n} memiliki tipe tidak didukung: {dtype}.')
        low = np.array([np.inf, np.inf, np.inf])
        high = np.array([-np.inf, -np.inf, -np.inf])
        total = len(vertices)
        for start in range(0, total, CHUNK_SIZE):
            chunk = _xyz_chunk(vertices[start: start + CHUNK_SIZE])
            if not np.isfinite(chunk).all():
                raise CropError(f'PLY mempunyai koordinat NaN/inf pada indeks {start}–{start + len(chunk)-1}.')
            low = np.minimum(low, chunk.min(axis=0))
            high = np.maximum(high, chunk.max(axis=0))
            if progress:
                progress(int(100 * (start + len(chunk)) / total))
        # Thin-axis scans are supported, but VTK box needs finite thickness.
        bounds = tuple(v for pair in zip(low, high) for v in pair)
        other = tuple(e.name for e in ply.elements if e.name != 'vertex')
        gaussian = any(n.startswith(('f_dc_', 'f_rest_', 'scale_', 'rot_'))
                       for n in names) or ('opacity' in names and 'scale_0' in names)
        return CloudDocument(path, ply, vertices, bounds, names, other, gaussian)
    except CropError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CropError(f'Gagal membuka PLY: {exc}') from exc


def selection_stats(doc: CloudDocument, roi: BoxSelection | PolygonSelection | BrushSelection,
                    *, progress=None, cancelled=None):
    selected = 0
    low = np.array([np.inf] * 3)
    high = np.array([-np.inf] * 3)
    for start in range(0, doc.count, CHUNK_SIZE):
        check_cancel(cancelled)
        xyz = _xyz_chunk(doc.vertices[start:start + CHUNK_SIZE])
        picked = xyz[roi.mask(xyz)]
        selected += len(picked)
        if len(picked):
            low = np.minimum(low, picked.min(axis=0))
            high = np.maximum(high, picked.max(axis=0))
        if progress:
            progress(40 * (start + len(xyz)) // doc.count)
    return selected, (None if not selected else tuple(v for pair in zip(low, high) for v in pair))


def _build_header(doc: CloudDocument, count: int) -> bytes:
    """Standard little-endian, scalar vertex-only PLY header."""
    lines = ['ply', 'format binary_little_endian 1.0',
             'comment Cropped by GS-PrepTools LiDAR Point Cloud Object Cropper',
             'comment Only vertex data is exported; other elements are excluded']
    for c in doc.ply.comments:
        if '\n' not in c and '\r' not in c and c.isascii() and not c.startswith('comment Cropped by'):
            lines.append('comment ' + c)
    for obj in doc.ply.obj_info:
        if '\n' not in obj and '\r' not in obj and obj.isascii():
            lines.append('obj_info ' + obj)
    lines.append(f'element vertex {count}')
    for name in doc.names:
        field = doc.vertices.dtype.fields[name][0]
        lines.append(f'property {PLY_TYPES[(field.kind, field.itemsize)]} {name}')
    lines.append('end_header')
    return ('\n'.join(lines) + '\n').encode('ascii', errors='strict')


def export_crop(doc: CloudDocument | LasDocument, roi: BoxSelection | PolygonSelection | BrushSelection | CenterSelection,
                output: str | Path, *,
                allow_drop_elements: bool = False, overwrite: bool = False,
                selection_history: dict | None = None,
                progress: Callable[[int], None] | None = None,
                cancelled: Callable[[], bool] | None = None) -> tuple[Path, Path, dict]:
    """Two-pass, memory-bounded full-resolution selection and atomic binary write."""
    if doc.path.suffix.lower() in LAS_SUFFIXES:
        from .las import export_las_crop
        return export_las_crop(doc, roi, output, overwrite=overwrite, progress=progress,
                               selection_history=selection_history, cancelled=cancelled)
    from .brush import BrushSelection
    from .center import CenterSelection
    check_cancel(cancelled)
    out = Path(output).expanduser().resolve()
    if out.suffix.lower() != '.ply':
        raise CropError('File keluaran harus berekstensi .ply.')
    if out == doc.path or (out.exists() and out.samefile(doc.path)):
        raise CropError('File asli tidak boleh ditimpa.')
    if not out.parent.is_dir():
        raise CropError('Folder output belum ada.')
    meta = out.with_name(out.stem + '_selection.json')
    if not overwrite and (out.exists() or meta.exists()):
        raise CropError('File output/metadata sudah ada. Pilih nama lain atau setujui overwrite.')
    if doc.other_elements and not allow_drop_elements:
        raise CropError('PLY mengandung element non-vertex: ' + ', '.join(doc.other_elements) +
                        '. Setujui ekspor point cloud (vertex-only) secara eksplisit.')
    srcstat = doc.path.stat()
    is_center = isinstance(roi, CenterSelection)
    is_polygon = not isinstance(roi, (BoxSelection, CenterSelection))
    is_brush = isinstance(roi, BrushSelection)
    source_hash = file_sha256(doc.path, cancelled=cancelled) if is_center or is_polygon or selection_history is not None else None
    count, bounds = selection_stats(doc, roi, progress=progress, cancelled=cancelled)
    if count == 0:
        raise CropError('Kotak tidak mengandung titik. Crop kosong tidak diekspor.')
    if progress:
        progress(40)
    # Keep exact per-property numeric values. Repack mixed-byte-order input to
    # little endian without touching coordinates or normalizing any attributes.
    out_dtype = np.dtype([(n, doc.vertices.dtype[n].newbyteorder('<')) for n in doc.names])
    with tempfile.TemporaryDirectory(prefix='.crop-', dir=out.parent) as work:
        staged = Path(work) / 'selected.ply'
        with staged.open('wb') as fp:
            fp.write(_build_header(doc, count))
            written = 0
            for start in range(0, doc.count, CHUNK_SIZE):
                check_cancel(cancelled)
                chunk = doc.vertices[start:start + CHUNK_SIZE]
                chosen = chunk[roi.mask(_xyz_chunk(chunk))]
                if len(chosen):
                    selected = np.asarray(chosen).astype(out_dtype, copy=False)
                    fp.write(selected.tobytes(order='C'))
                written += len(chosen)
                if progress:
                    progress(40 + int(45 * min(1., (start + len(chunk)) / doc.count)))
            if written != count:
                raise CropError('Jumlah titik berubah saat ekspor. Output dibatalkan.')
            fp.flush()
            os.fsync(fp.fileno())
        # Independently verify header and entire binary payload with a streaming
        # reader. No mmap is held open when Windows performs the atomic rename.
        header = _build_header(doc, count)
        offset = 0
        with staged.open('rb') as fp:
            if fp.read(len(header)) != header:
                raise CropError('Verifikasi header PLY gagal.')
            for start in range(0, doc.count, CHUNK_SIZE):
                check_cancel(cancelled)
                chunk = doc.vertices[start:start + CHUNK_SIZE]
                chosen = chunk[roi.mask(_xyz_chunk(chunk))]
                size = len(chosen) * out_dtype.itemsize
                payload = fp.read(size)
                if len(payload) != size:
                    raise CropError('Verifikasi PLY gagal: output terpotong.')
                readback = np.frombuffer(payload, dtype=out_dtype)
                for n in doc.names:
                    original = np.asarray(chosen[n]).astype(out_dtype[n], copy=False)
                    if original.tobytes() != np.asarray(readback[n]).tobytes():
                        raise CropError(f'Verifikasi gagal: atribut {n} berbeda.')
                offset += len(chosen)
                if progress:
                    progress(85 + int(13 * min(1., (start + len(chunk)) / doc.count)))
            if offset != count or fp.read(1):
                raise CropError('Verifikasi PLY gagal: panjang data tidak sesuai.')
        payload = {
            'schema_version': HISTORY_SCHEMA if is_brush else (3 if is_polygon else 1),
            'tool': 'GS-PrepTools LiDAR Point Cloud Object Cropper MVP',
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'input_file': str(doc.path), 'input_size_bytes': srcstat.st_size,
            'input_modified_ns': srcstat.st_mtime_ns,
            'input_format': 'ascii' if doc.ply.text else 'binary',
            'input_classification': doc.classification,
            'output_file': str(out), 'output_format': 'binary_little_endian',
            'source_points': doc.count, 'retained_points': count,
            'retained_percent': round(100 * count / doc.count, 5),
            'selected_bounds_xyz': list(bounds) if bounds else None,
            'selection': roi.to_dict(), 'tolerance': 1e-7,
            'preserved_vertex_properties': list(doc.names),
            'excluded_nonvertex_elements': list(doc.other_elements),
            'coordinate_transform': 'none', 'smoothing': 'none', 'denoising': 'none',
            'verification': 'full byte-exact field comparison with input selected vertices',
            'caution': 'Cropping does not perform LiDAR-to-reconstruction registration or alignment.',
        }
        if is_polygon:
            payload.update(input_sha256=source_hash, roi_kind='Brush' if is_brush else 'Polygon')
        if is_center:
            payload.update(input_sha256=source_hash, roi_kind=roi.shape)
        if selection_history is not None:
            payload.update(schema_version=HISTORY_SCHEMA, input_sha256=source_hash,
                           selection_history=selection_history)
        staged_meta = Path(work) / 'selection.json'
        write_json_atomic(staged_meta, payload)
        current = doc.path.stat()
        if (current.st_size, current.st_mtime_ns) != (srcstat.st_size, srcstat.st_mtime_ns):
            raise CropError('File sumber berubah saat ekspor.')
        check_cancel(cancelled)
        publish_crop(staged, staged_meta, out, meta, overwrite)
        if progress:
            progress(100)
        return out, meta, payload


def publish_crop(staged, staged_meta, out, meta, overwrite):
    """Publish the two validated artifacts and restore the previous crop if JSON fails."""
    for path in (out, meta):
        if path.exists() and (not overwrite or not path.is_file()):
            raise CropError(f'Output sudah ada atau bukan file biasa: {path}')
    backup = staged.parent / 'previous-output'
    if out.exists():
        os.link(out, backup)
    os.replace(staged, out)
    try:
        os.replace(staged_meta, meta)
    except OSError:
        if backup.exists():
            os.replace(backup, out)
        else:
            out.unlink()
        raise


def write_json_atomic(output: Path, payload: dict):
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.json.tmp',
                                         dir=str(output.parent), delete=False) as fp:
            name = fp.name
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(name, output)
        name = None
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def file_sha256(path: Path, *, cancelled=None) -> str:
    check_cancel(cancelled)
    digest = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            check_cancel(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def read_selection_metadata(path: str | Path, doc: CloudDocument | LasDocument) -> dict:
    with open(path, 'r', encoding='utf-8') as fp:
        data = json.load(fp)
    # Prevent mistakenly replaying ROI from a different SLAM session.
    size = data.get('input_size_bytes')
    if size is not None and size != doc.file_size:
        raise CropError('Ukuran file berbeda dari file sumber metadata. Seleksi ditolak.')
    if 'input_file' in data and Path(data['input_file']).name != doc.path.name:
        raise CropError('Nama file berbeda dari file sumber metadata. Seleksi ditolak.')
    from .polygon import POLYGON_TYPE
    from .brush import BRUSH_TYPE
    selection = data['selection']
    has_history = 'selection_history' in data
    schema = data.get('schema_version')
    brush = selection.get('type') == BRUSH_TYPE
    if ((has_history and schema not in (4, HISTORY_SCHEMA))
            or (schema in (4, HISTORY_SCHEMA) and not has_history and not (brush and schema == HISTORY_SCHEMA))
            or (brush and schema != HISTORY_SCHEMA)):
        raise CropError('Skema history seleksi tidak valid.')
    if has_history or selection.get('type') in (POLYGON_TYPE, BRUSH_TYPE):
        if not data.get('input_sha256') or data.get('source_points') != doc.count:
            raise CropError('Identitas atau jumlah titik sumber metadata seleksi tidak valid.')
    if 'input_sha256' in data and file_sha256(doc.path) != data['input_sha256']:
        raise CropError('SHA-256 berbeda dari file sumber metadata. Seleksi ditolak.')
    return data


def load_selection_json(path: str | Path, doc: CloudDocument | LasDocument) -> BoxSelection | PolygonSelection | BrushSelection:
    from .history import load_history_json
    return load_history_json(path, doc).selection
