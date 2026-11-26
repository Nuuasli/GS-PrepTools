"""Replayable selections in the camera view, independent of Qt and VTK."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .core import BoxSelection, CropError, box_kind

POLYGON_TYPE = 'viewport_polygon_sequence'
MAX_VERTICES = 256
EDGE_EPSILON = 1e-10  # normalized viewport coordinates


def screen_to_uv(x, y, width, height, viewport):
    """Convert Qt logical pixels (top left) to normalized renderer coordinates."""
    left, bottom, right, top = viewport
    return ((x / width - left) / (right - left),
            (y / height - (1 - top)) / (top - bottom))


def uv_to_screen(u, v, width, height, viewport):
    left, bottom, right, top = viewport
    return ((left + u * (right - left)) * width,
            (1 - top + v * (top - bottom)) * height)


@dataclass(frozen=True)
class CameraProjection:
    world_to_clip: np.ndarray
    world_to_view: np.ndarray
    clipping_range: tuple[float, float]
    mode: str
    viewport: tuple[float, float, float, float]
    framebuffer_size: tuple[int, int]
    device_pixel_ratio: float

    def __post_init__(self):
        for name in ('world_to_clip', 'world_to_view'):
            matrix = np.array(getattr(self, name), dtype=np.float64, copy=True)
            if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
                raise CropError('Matriks kamera poligon tidak valid.')
            matrix.setflags(write=False)
            object.__setattr__(self, name, matrix)
        near, far = self.clipping_range
        left, bottom, right, top = self.viewport
        if (self.mode not in ('perspective', 'orthographic')
                or not np.isfinite([near, far, self.device_pixel_ratio]).all()
                or far <= near or self.device_pixel_ratio <= 0
                or not (0 <= left < right <= 1 and 0 <= bottom < top <= 1)
                or len(self.framebuffer_size) != 2 or min(self.framebuffer_size) <= 0):
            raise CropError('Parameter viewport atau kamera tidak valid.')

    def to_dict(self):
        return {
            'world_to_clip': self.world_to_clip.tolist(),
            'world_to_view': self.world_to_view.tolist(),
            'clipping_range': list(self.clipping_range), 'mode': self.mode,
            'viewport': list(self.viewport), 'framebuffer_size': list(self.framebuffer_size),
            'device_pixel_ratio': self.device_pixel_ratio,
        }


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    def overlaps(lo, hi, a0, a1):
        return max(min(lo, hi), min(a0, a1)) <= min(max(lo, hi), max(a0, a1))

    return (overlaps(a[0], b[0], c[0], d[0]) and overlaps(a[1], b[1], c[1], d[1])
            and _cross(a, b, c) * _cross(a, b, d) <= 0
            and _cross(c, d, a) * _cross(c, d, b) <= 0)


def _validated_vertices(vertices):
    vertices = np.asarray(vertices, dtype=np.float64)
    if (vertices.ndim != 2 or vertices.shape[1] != 2 or
            not 3 <= len(vertices) <= MAX_VERTICES or
            not np.isfinite(vertices).all() or np.any((vertices < 0) | (vertices > 1))):
        raise CropError(f'Poligon memerlukan 3–{MAX_VERTICES} titik di viewport.')
    points = [tuple(vertex) for vertex in vertices]
    if len(set(points)) != len(points):
        raise CropError('Poligon memiliki titik berulang.')
    edges = list(zip(points, points[1:] + points[:1]))
    area2 = sum(a[0] * b[1] - a[1] * b[0] for a, b in edges)
    if abs(area2) <= EDGE_EPSILON:
        raise CropError('Poligon degenerat atau terlalu kecil.')
    for i, j in combinations(range(len(edges)), 2):
        if j - i not in (1, len(edges) - 1) and _intersects(*edges[i], *edges[j]):
            raise CropError('Garis poligon saling berpotongan.')
    return tuple(points)


def _inside(vertices, uv):
    x, y = uv.T
    inside = np.zeros(len(x), dtype=bool)
    boundary = np.zeros(len(x), dtype=bool)
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:] + vertices[:1]):
        dx, dy = bx - ax, by - ay
        cross = (x - ax) * dy - (y - ay) * dx
        boundary |= ((np.abs(cross) <= EDGE_EPSILON * np.hypot(dx, dy))
                     & (x >= min(ax, bx) - EDGE_EPSILON) & (x <= max(ax, bx) + EDGE_EPSILON)
                     & (y >= min(ay, by) - EDGE_EPSILON) & (y <= max(ay, by) + EDGE_EPSILON))
        if dy:
            inside ^= ((ay > y) != (by > y)) & (x < ax + (y - ay) * dx / dy)
    return inside | boundary


def project_selection_uv(camera, interval, xyz):
    near = max(interval[0], camera.clipping_range[0])
    far = min(interval[1], camera.clipping_range[1])
    view_z = camera.world_to_view[2]
    depth = -(np.einsum('ij,j->i', xyz, view_z[:3]) + view_z[3])
    candidates = np.flatnonzero((depth >= near) & (depth <= far) & (depth > 0))
    matrix = camera.world_to_clip
    clip = np.einsum('ij,kj->ik', xyz[candidates], matrix[:, :3]) + matrix[:, 3]
    w = clip[:, 3]
    valid = (w > 0) & np.all(np.abs(clip[:, :3]) <= w[:, None] * (1 + EDGE_EPSILON), axis=1)
    uv = clip[valid, :2] / w[valid, None] * [.5, -.5] + .5
    return candidates[valid], uv


@dataclass(frozen=True)
class PolygonOperation:
    kind: str
    vertices: tuple
    camera: CameraProjection
    depth: tuple[float, float]

    def __post_init__(self):
        if self.kind not in ('keep', 'remove'):
            raise CropError('Operasi poligon tidak dikenal.')
        near, far = self.depth
        if not np.isfinite([near, far]).all() or not 0 <= near < far:
            raise CropError('Depth Near harus >= 0 dan lebih kecil dari Depth Far.')
        object.__setattr__(self, 'vertices', _validated_vertices(self.vertices))

    def mask(self, xyz):
        candidates, uv = project_selection_uv(self.camera, self.depth, xyz)
        result = np.zeros(len(xyz), dtype=bool)
        result[candidates] = _inside(self.vertices, uv)
        return result

    def to_dict(self):
        return {'operation': self.kind, 'vertices_uv': [list(p) for p in self.vertices],
                'camera': self.camera.to_dict(), 'depth': list(self.depth)}

    @classmethod
    def from_dict(cls, data):
        return cls(data['operation'], data['vertices_uv'], CameraProjection(**data['camera']), data['depth'])


@dataclass(frozen=True)
class PolygonSelection:
    initial_box: BoxSelection | None
    operations: tuple[PolygonOperation, ...]

    def mask(self, xyz):
        active = self.initial_box.mask(xyz) if self.initial_box else np.ones(len(xyz), dtype=bool)
        for operation in self.operations:
            indices = np.flatnonzero(active)
            if not len(indices):
                break
            hits = operation.mask(xyz[indices])
            active[indices] = hits if operation.kind == 'keep' else ~hits
        return active

    def to_dict(self):
        return {
            'type': POLYGON_TYPE,
            'initial_box': self.initial_box.to_dict() if self.initial_box else None,
            'initial_box_kind': box_kind(self.initial_box) if self.initial_box else None,
            'operations': [op.to_dict() for op in self.operations],
            'vertex_coordinates': 'normalized viewport UV, origin top-left',
            'depth_coordinates': 'positive distance along camera view axis in source units',
        }

    @classmethod
    def from_dict(cls, data):
        box = data['initial_box']
        operations = tuple(PolygonOperation.from_dict(op) for op in data['operations'])
        if not operations:
            raise CropError('Metadata poligon tidak memiliki operasi.')
        return cls(BoxSelection.from_dict(box) if box is not None else None, operations)
