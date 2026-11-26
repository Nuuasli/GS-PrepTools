"""GS-PrepTools web adapter for the headless desktop LiDAR core."""

import struct
from pathlib import Path

import numpy as np

from app.models.lidar import CropRegion
from lidar_cropper.center import CenterSelection
from lidar_cropper.core import (
    CHUNK_SIZE, PLY_TYPES, CropError, _xyz_chunk, check_cancel, export_crop, file_sha256, load_cloud,
)
from lidar_cropper.las import LasDocument, _ply_dtype, _xyz

QUALITIES = {"draft": 25_000, "standard": 100_000, "high": 250_000}
PREVIEW_DTYPE = np.dtype([("xyz", "<f8", (3,)), ("rgb", "u1", (3,)), ("intensity", "u1")])
PLY_HEADER_LIMIT = 64 * 1024
ASCII_PLY_LIMIT = 32 * 1024 * 1024
LAS_METADATA_LIMIT = 16 * 1024 * 1024
PLY_SCALARS = {name: size for (_, size), name in PLY_TYPES.items()}
PLY_SCALARS.update(int8=1, uint8=1, int16=2, uint16=2, int32=4, uint32=4, float32=4, float64=8)


def _check_ply(path: Path, size: int):
    with path.open("rb") as stream:
        header = stream.read(PLY_HEADER_LIMIT)
    if not header.startswith((b"ply\n", b"ply\r\n")):
        raise CropError("File does not have a PLY header.")
    end = 0
    for line in header.splitlines(keepends=True):
        end += len(line)
        if line.rstrip(b"\r\n") == b"end_header" and line.endswith(b"\n"):
            break
    else:
        raise CropError("PLY header is missing or exceeds 64 KiB.")
    try:
        lines = [line.split() for line in header[:end].decode("ascii").splitlines()]
        formats = [line[1:] for line in lines if line and line[0] == "format"]
        elements = [line[1:] for line in lines if line and line[0] == "element"]
        if len(elements) != 1 or len(elements[0]) != 2 or elements[0][0] != "vertex":
            raise CropError("Web cropping requires vertex-only PLY. Mesh faces and other elements are unsupported.")
        count = int(elements[0][1])
        properties = [line[1:] for line in lines if line and line[0] == "property"]
        if any(len(p) != 2 or p[0] not in PLY_SCALARS for p in properties):
            raise CropError("PLY vertices must have scalar properties.")
        names = [p[1] for p in properties]
        if len(names) != len(set(names)) or not {"x", "y", "z"}.issubset(names) or count <= 0:
            raise CropError("PLY needs nonempty vertices and unique x, y, z properties.")
        width = sum(PLY_SCALARS[p[0]] for p in properties)
        if formats == [["ascii", "1.0"]]:
            if count * len(properties) * 2 - 1 > size - end:
                raise CropError("PLY vertex count is inconsistent with the file size.")
            if max(size, count * width) > ASCII_PLY_LIMIT:
                raise CropError("ASCII PLY is limited to 32 MiB. Use binary PLY for large clouds.")
        elif formats in ([["binary_little_endian", "1.0"]], [["binary_big_endian", "1.0"]]):
            if size - end != count * width:
                raise CropError("PLY vertex data is incomplete or does not match its header.")
        else:
            raise CropError("Unsupported PLY encoding.")
    except (UnicodeError, ValueError) as exc:
        raise CropError("Invalid PLY header.") from exc


def _check_las(path: Path, size: int, decoded_limit: int):
    with path.open("rb") as stream:
        header = stream.read(375)
    if len(header) < 227 or header[:4] != b"LASF":
        raise CropError("File does not have a valid LAS/LAZ header.")
    header_size, data_offset = struct.unpack_from("<HI", header, 94)
    point_format, width, count = struct.unpack_from("<BHI", header, 104)
    compressed = bool(point_format & 0x80)
    if compressed != (path.suffix == ".laz"):
        raise CropError("File extension does not match the LAS/LAZ compression.")
    if not 227 <= header_size <= data_offset <= min(size, LAS_METADATA_LIMIT):
        raise CropError("Invalid or oversized LAS/LAZ header records.")
    if header[24:26] == b"\x01\x04":
        if header_size < 375 or len(header) < 375:
            raise CropError("Incomplete LAS 1.4 header.")
        evlr_start, evlr_count, count = struct.unpack_from("<QIQ", header, 235)
        if evlr_count and not data_offset <= evlr_start <= size:
            raise CropError("Invalid LAS extended-record offset.")
        if evlr_count and size - evlr_start > LAS_METADATA_LIMIT:
            raise CropError("LAS extended records exceed 16 MiB.")
    if not width or not count or count * width > decoded_limit:
        raise CropError("Decoded point records exceed the server limit or the cloud is empty.")
    if not compressed and data_offset + width * count > size:
        raise CropError("LAS point records are incomplete.")


def _display_channel(values, *, fixed_range=False):
    values = np.asarray(values)
    converted = np.nan_to_num(values.astype(np.float64), nan=0, posinf=0, neginf=0)
    if fixed_range and values.dtype.kind == "u":
        low, high = 0, np.iinfo(values.dtype).max
    elif fixed_range:
        low, high = 0, 1 if converted.max() <= 1 else 255
    else:
        low, high = float(converted.min()), float(converted.max())
    if high <= low:
        return np.full(len(values), 160, dtype=np.uint8)
    return np.rint(np.clip((converted - low) / (high - low), 0, 1) * 255).astype(np.uint8)


def prepare_source(path: Path, *, decoded_limit: int, progress, verify):
    size = path.stat().st_size
    if path.suffix == ".ply":
        _check_ply(path, size)
    else:
        _check_las(path, size, decoded_limit)
    doc = load_cloud(path, progress)
    points, attrs = (doc.preview(QUALITIES["high"], progress) if isinstance(doc, LasDocument)
                     else doc.preview(QUALITIES["high"]))
    bounds = np.asarray(doc.bounds).reshape(3, 2)
    if not np.isfinite(bounds).all() or np.abs(bounds).max() > 1e30:
        raise CropError("Coordinates are outside the numeric range of the web viewer.")
    data = np.zeros(len(points), dtype=PREVIEW_DTYPE)
    data["xyz"] = points
    colors = ("red", "green", "blue")
    has_rgb = all(key in attrs for key in colors) and any(np.any(attrs[key]) for key in colors)
    if isinstance(doc, LasDocument):
        has_rgb = doc.rgb_status == "available"
        # Some producers store 8-bit color in 16-bit LAS channels.
        if has_rgb and max(int(attrs[key].max()) for key in colors) <= 255:
            attrs.update({key: attrs[key].astype(np.uint8) for key in colors})
    if has_rgb:
        data["rgb"] = np.column_stack([_display_channel(attrs[key], fixed_range=True) for key in colors])
    if "intensity" in attrs:
        data["intensity"] = _display_channel(attrs["intensity"])
    counts = {}
    for key, limit in QUALITIES.items():
        count = min(len(data), limit)
        verify()
        sample = data[np.linspace(0, len(data)-1, count, dtype=np.int64)]
        sample.tofile(path.parent / f"preview-{key}.bin")
        counts[key] = count
    info = {
        "format": path.suffix[1:], "classification": doc.classification, "point_count": doc.count,
        "min_xyz": bounds[:, 0].tolist(), "max_xyz": bounds[:, 1].tolist(),
        "attributes": list(doc.names), "has_rgb": has_rgb, "has_intensity": "intensity" in attrs,
        "preview_counts": counts, "axis_units": [], "crs": None, "ply_derivative": False,
    }
    if isinstance(doc, LasDocument):
        try:
            _ply_dtype(doc)
        except CropError:
            pass
        else:
            info["ply_derivative"] = True
        info.update(axis_units=doc.spatial["axis_units"], crs=doc.spatial.get("crs_name") or doc.spatial["crs_wkt"],
                    scale=doc.header.scales.tolist(), offset=doc.header.offsets.tolist())
    return info


def preview_mask(path: Path, selection: CropRegion):
    records = np.fromfile(path, dtype=PREVIEW_DTYPE, count=QUALITIES["high"])
    return CenterSelection(**selection.model_dump()).mask(records["xyz"]).astype("u1").tobytes()


def count_selection(source: Path, selection: CropRegion, progress, cancelled):
    """Count the same full-resolution selection used by the export writer."""
    check_cancel(cancelled)
    doc = load_cloud(source, lambda percent: progress(percent // 5))
    roi = CenterSelection(**selection.model_dump())
    if isinstance(doc, LasDocument):
        chunks = (_xyz(points) for points in doc.chunks())
    else:
        chunks = (_xyz_chunk(doc.vertices[start:start + CHUNK_SIZE])
                  for start in range(0, doc.count, CHUNK_SIZE))
    selected = scanned = 0
    for points in chunks:
        check_cancel(cancelled)
        selected += int(np.count_nonzero(roi.mask(points)))
        scanned += len(points)
        progress(20 + 80 * scanned // doc.count)
    return selected


def export_selection(source, output, request, expected_hash, progress, cancelled):
    doc = load_cloud(source, lambda percent: progress(percent * 4 // 100))
    _, desktop_json, metadata = export_crop(
        doc, CenterSelection(**request.selection.model_dump()), output, progress=progress, cancelled=cancelled,
    )
    if metadata["input_sha256"] != expected_hash or file_sha256(source, cancelled=cancelled) != expected_hash:
        raise CropError("Source SHA-256 changed. Upload the source again.")
    desktop_json.unlink()
    return metadata
