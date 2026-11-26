"""Depth-aware projected brush strokes and mixed polygon/brush replay."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .core import BoxSelection, CropError, box_kind
from .polygon import CameraProjection, PolygonOperation, project_selection_uv

BRUSH_TYPE = 'viewport_brush_sequence'
BRUSH_ACTIONS = ('brush_remove', 'brush_restore')
MAX_STROKE_POINTS = 1024


def _stroke_hits(points, path, radius):
    padding = radius + 1e-8
    candidates = np.flatnonzero(np.all(
        (points >= path.min(axis=0) - padding) & (points <= path.max(axis=0) + padding), axis=1,
    ))
    order = candidates[np.argsort(points[candidates, 0])]
    sorted_x = points[order, 0]
    hit = np.zeros(len(points), dtype=bool)
    for a, b in zip(path, path[1:] if len(path) > 1 else path):
        low = np.minimum(a, b) - padding
        high = np.maximum(a, b) + padding
        start, stop = sorted_x.searchsorted(low[0]), sorted_x.searchsorted(high[0], side='right')
        indices = order[start:stop]
        y = points[indices, 1]
        indices = indices[(y >= low[1]) & (y <= high[1]) & ~hit[indices]]
        delta = points[indices] - a
        vector = b - a
        length2 = vector @ vector
        if length2:
            delta -= np.clip(np.einsum('ij,j->i', delta, vector) / length2, 0., 1.)[:, None] * vector
        hit[indices] = np.einsum('ij,ij->i', delta, delta) <= padding ** 2
    return hit


@dataclass(frozen=True)
class BrushOperation:
    kind: str
    points_uv: tuple
    radius: float
    camera: CameraProjection
    depth: tuple[float, float]

    def __post_init__(self):
        points = np.asarray(self.points_uv, dtype=np.float64)
        if (points.ndim != 2 or points.shape[1] != 2 or not 1 <= len(points) <= MAX_STROKE_POINTS
                or not np.isfinite(points).all() or np.any((points < 0.) | (points > 1.))):
            raise CropError('Stroke brush kosong atau berisi titik viewport yang tidak valid.')
        if self.kind not in BRUSH_ACTIONS or not np.isfinite(self.radius) or not 1. <= self.radius <= 400.:
            raise CropError('Mode atau radius brush tidak valid.')
        near, far = self.depth
        if not np.isfinite([near, far]).all() or not 0. <= near < far:
            raise CropError('Depth Near harus >= 0 dan lebih kecil dari Depth Far.')
        object.__setattr__(self, 'points_uv', tuple(tuple(row) for row in points))
        object.__setattr__(self, 'depth', (near, far))

    def mask(self, xyz):
        indices, uv = project_selection_uv(self.camera, self.depth, xyz)
        left, bottom, right, top = self.camera.viewport
        size = np.asarray(self.camera.framebuffer_size) * [right - left, top - bottom]
        radius = self.radius * self.camera.device_pixel_ratio
        result = np.zeros(len(xyz), dtype=bool)
        result[indices[_stroke_hits(uv * size, np.asarray(self.points_uv) * size, radius)]] = True
        return result

    def to_dict(self):
        return {'operation': self.kind, 'points_uv': [list(p) for p in self.points_uv],
                'radius_logical_px': self.radius, 'camera': self.camera.to_dict(), 'depth': list(self.depth)}

    @classmethod
    def from_dict(cls, data):
        return cls(data['operation'], data['points_uv'], data['radius_logical_px'],
                   CameraProjection(**data['camera']), data['depth'])


def decode_operation(data):
    if data.get('operation') in BRUSH_ACTIONS:
        return BrushOperation.from_dict(data)
    return PolygonOperation.from_dict(data)


@dataclass(frozen=True)
class BrushSelection:
    initial_box: BoxSelection | None
    operations: tuple[PolygonOperation | BrushOperation, ...]

    def mask(self, xyz):
        allowed = self.initial_box.mask(xyz) if self.initial_box else np.ones(len(xyz), dtype=bool)
        active = allowed.copy()
        for op in self.operations:
            if isinstance(op, PolygonOperation):
                indices = np.flatnonzero(allowed)
                hits = op.mask(xyz[indices])
                allowed[indices] = hits if op.kind == 'keep' else ~hits
                active &= allowed
            elif op.kind == 'brush_remove':
                indices = np.flatnonzero(active)
                active[indices] = ~op.mask(xyz[indices])
            else:
                indices = np.flatnonzero(allowed & ~active)
                active[indices] = op.mask(xyz[indices])
        return active

    def to_dict(self):
        return {
            'type': BRUSH_TYPE,
            'initial_box': self.initial_box.to_dict() if self.initial_box else None,
            'initial_box_kind': box_kind(self.initial_box) if self.initial_box else None,
            'operations': [op.to_dict() for op in self.operations],
            'restore_domain': 'initial ROI intersected with all polygon decisions so far',
        }

    @classmethod
    def from_dict(cls, data):
        box = data['initial_box']
        operations = tuple(decode_operation(op) for op in data['operations'])
        if not any(isinstance(op, BrushOperation) for op in operations):
            raise CropError('Histori brush tidak memiliki stroke.')
        return cls(BoxSelection.from_dict(box) if box is not None else None, operations)
