"""Center-based selection in native source coordinates."""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from .core import CropError


@dataclass(frozen=True)
class CenterSelection:
    shape: str
    center: tuple[float, float, float]
    radius: float
    height: float | None = None
    axis: str = "z"

    def __post_init__(self):
        if self.shape not in ("sphere", "cylinder") or self.axis not in "xyz" or len(self.axis) != 1:
            raise CropError("Invalid crop shape or cylinder axis.")
        if len(self.center) != 3 or not all(map(isfinite, self.center)):
            raise CropError("Center must contain three finite coordinates.")
        if not isfinite(self.radius) or self.radius <= 0:
            raise CropError("Radius must be positive and finite.")
        if self.shape == "cylinder" and (
            self.height is None or not isfinite(self.height) or self.height <= 0
        ):
            raise CropError("Cylinder height must be positive and finite.")

    def mask(self, xyz: np.ndarray) -> np.ndarray:
        # Using hypot avoids overflow when the source coordinates are large.
        with np.errstate(over="ignore"):
            offsets = np.asarray(xyz, dtype=np.float64) - self.center
            if self.shape == "sphere":
                return np.hypot(np.hypot(offsets[:, 0], offsets[:, 1]), offsets[:, 2]) <= self.radius
            axis = "xyz".index(self.axis)
            first, second = (index for index in range(3) if index != axis)
            return ((np.hypot(offsets[:, first], offsets[:, second]) <= self.radius)
                    & (np.abs(offsets[:, axis]) <= self.height / 2))

    def to_dict(self) -> dict:
        data = {"shape": self.shape, "center": list(self.center), "radius": self.radius}
        if self.shape == "cylinder":
            data.update(height=self.height, axis=self.axis)
        return data
