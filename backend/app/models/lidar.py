"""Portable selection and validated web API inputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, FiniteFloat, Field, model_validator

PreviewQuality = Literal["draft", "standard", "high"]
OutputFormat = Literal["ply", "las", "laz"]
DownloadKind = Literal["output", "selection"]


class CropRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shape: Literal["sphere", "cylinder"]
    center: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    radius: FiniteFloat = Field(gt=0)
    height: FiniteFloat | None = Field(default=None, gt=0)
    axis: Literal["x", "y", "z"] = "z"

    @model_validator(mode="after")
    def check_shape(self):
        if self.shape == "cylinder" and self.height is None:
            raise ValueError("Cylinder height is required.")
        return self


class CropRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: CropRegion
    output_format: OutputFormat
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accept_derivative: bool = False


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: CropRegion
    quality: PreviewQuality = "standard"
    include_full_count: bool = False
