# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings, result and error types shared by every pipeline step."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

CONVERTIBLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}

ALL_MAPS = ("BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC", "AO", "EMISSION")

UV_MODES = ("GENERATE", "EXISTING")


@dataclass
class RetopoSettings:
    name: str = ""                      # base name for outputs ("" = derive from first source)

    # Retopology
    low_poly_object: str = ""           # use this object as the low-poly ("" = QuadriFlow)
    target_faces: int = 5000
    voxel_mode: str = "AUTO"            # AUTO | ALWAYS | NEVER
    voxel_resolution: int = 256         # voxels across largest bbox dimension
    use_preserve_sharp: bool = False
    use_preserve_boundary: bool = False
    use_mesh_symmetry: bool = False
    smooth_shading: bool = True
    seed: int = 0

    # UVs
    uv_mode: str = "GENERATE"           # GENERATE | EXISTING (EXISTING needs low_poly_object)
    uv_method: str = "SMART"            # SMART | LIGHTMAP
    uv_angle_limit: float = 66.0        # degrees (Smart UV)
    uv_island_margin: float = 0.005

    # Baking
    bake_maps: tuple = ("BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC")
    texture_size: int = 2048
    bake_samples: int = 16
    bake_margin: int = 16
    cage_extrusion: float = 0.0         # 0 = auto (1% of bbox diagonal)
    max_ray_distance: float = 0.0       # 0 = auto (5% of bbox diagonal)
    device: str = "CPU"                 # CPU | GPU
    output_dir: str = ""                # "" = pack images into the .blend
    image_format: str = "PNG"           # PNG | JPEG | OPEN_EXR | TIFF

    # Scene housekeeping
    keep_high_poly: bool = False
    hide_sources: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "RetopoSettings":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        if "bake_maps" in clean:
            clean["bake_maps"] = tuple(clean["bake_maps"])
        return cls(**clean)


@dataclass
class RetopoResult:
    object_name: str = ""
    material_name: str = ""
    source_objects: list = field(default_factory=list)
    source_faces: int = 0
    result_faces: int = 0
    used_voxel_remesh: bool = False
    low_poly_object: str = ""                    # provided low-poly ("" = QuadriFlow)
    uvs_generated: bool = True
    images: dict = field(default_factory=dict)   # map -> filepath or "<packed>"
    timings: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class SmartRetopoError(RuntimeError):
    pass


ProgressFn = Optional[Callable[[str, float], None]]
