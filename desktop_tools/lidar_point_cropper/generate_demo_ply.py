"""Produce deterministic colored synthetic statue-like cloud + surrounding floor."""
from pathlib import Path
import numpy as np
from plyfile import PlyData, PlyElement

rng = np.random.default_rng(2026)
# Synthetic stepped cylinder (object) + floor plane (noise outside ROI).
n = 60000
ang = rng.uniform(0, 2 * np.pi, n)
z = rng.uniform(0, 3, n)
r = 0.45 + 0.1 * np.cos(7 * ang) * (0.5 + 0.5 * np.cos(2 * z))
x = 1.0 + r * np.cos(ang)
y = 2.0 + r * np.sin(ang)
nf = 18000
fx = rng.uniform(-2, 4, nf)
fy = rng.uniform(-2, 5, nf)
fz = rng.normal(0, 0.01, nf)
xyz = np.vstack((np.column_stack((x, y, z)), np.column_stack((fx, fy, fz))))
vertices = np.empty(len(xyz), dtype=[('x','f4'),('y','f4'),('z','f4'),
                                    ('red','u1'),('green','u1'),('blue','u1'),
                                    ('intensity','f4'),('nx','f4'),('ny','f4'),('nz','f4')])
for i, field in enumerate(('x','y','z')):
    vertices[field] = xyz[:, i]
vertices['red'] = 177
vertices['green'] = 106
vertices['blue'] = 68
vertices['intensity'] = rng.uniform(0, 100, len(vertices))
vertices['nx'] = 0
vertices['ny'] = 0
vertices['nz'] = 1
out = Path(__file__).resolve().parent / 'demo_scan.ply'
PlyData([PlyElement.describe(vertices, 'vertex')], text=False, byte_order='<').write(str(out))
print(f'Created {out} ({len(vertices):,} points)')
