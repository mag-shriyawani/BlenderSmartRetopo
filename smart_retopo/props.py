# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared property definitions (used by the scene settings group and the operator)."""

from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import core

MAP_ITEMS = [
    ("BASE_COLOR", "Base Color", "Principled Base Color (lighting independent)"),
    ("NORMAL", "Normal", "Tangent-space normal map"),
    ("ROUGHNESS", "Roughness", "Principled Roughness"),
    ("METALLIC", "Metallic", "Principled Metallic"),
    ("AO", "Ambient Occlusion", "Ambient occlusion"),
    ("EMISSION", "Emission", "Emission"),
]


class SmartRetopoProps:
    name: StringProperty(name="Name", default="",
                         description="Base name for generated data (empty = use source name)")

    low_poly_object: StringProperty(
        name="Low-Poly Mesh", default="",
        description="Use this object as the low-poly instead of generating one with QuadriFlow "
                    "(empty = generate). The object itself is not modified")
    target_faces: IntProperty(name="Target Faces", default=5000, min=10, soft_max=200000)
    voxel_mode: EnumProperty(
        name="Voxel Pre-pass",
        items=[
            ("AUTO", "Auto", "Voxel remesh when combining several objects, when non-manifold, or if QuadriFlow fails"),
            ("ALWAYS", "Always", "Always voxel remesh before QuadriFlow (robust, fuses intersecting parts)"),
            ("NEVER", "Never", "Run QuadriFlow directly on the combined mesh"),
        ],
        default="AUTO",
    )
    voxel_resolution: IntProperty(name="Voxel Resolution", default=256, min=16, soft_max=1024,
                                  description="Voxels across the largest bounding-box dimension")
    use_preserve_sharp: BoolProperty(name="Preserve Sharp", default=False)
    use_preserve_boundary: BoolProperty(name="Preserve Boundary", default=False)
    use_mesh_symmetry: BoolProperty(name="Use Symmetry", default=False)
    smooth_shading: BoolProperty(name="Smooth Shading", default=True)
    seed: IntProperty(name="Seed", default=0, min=0)

    uv_mode: EnumProperty(name="UVs", items=[
        ("GENERATE", "Generate", "Unwrap the low-poly with the UV method below (replaces its UV maps)"),
        ("EXISTING", "Use Existing", "Bake into the provided low-poly's existing UV map (its render UV map)"),
    ], default="GENERATE")
    uv_method: EnumProperty(name="UV Method", items=[
        ("SMART", "Smart UV Project", ""), ("LIGHTMAP", "Lightmap Pack", "")], default="SMART")
    uv_angle_limit: FloatProperty(name="Angle Limit", default=66.0, min=1.0, max=89.0, subtype="NONE")
    uv_island_margin: FloatProperty(name="Island Margin", default=0.005, min=0.0, max=0.2, precision=4)

    bake_maps: EnumProperty(name="Maps", items=MAP_ITEMS, options={"ENUM_FLAG"},
                            default={"BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC"})
    texture_size: IntProperty(name="Resolution", default=2048, min=64, max=16384)
    bake_samples: IntProperty(name="Samples", default=16, min=1, soft_max=512)
    bake_margin: IntProperty(name="Margin (px)", default=16, min=0, max=128)
    cage_extrusion: FloatProperty(name="Extrusion", default=0.0, min=0.0, unit="LENGTH",
                                  description="0 = auto (1% of bounding-box diagonal). Increase it if a "
                                              "provided low-poly sits further from the surface")
    max_ray_distance: FloatProperty(name="Max Ray Distance", default=0.0, min=0.0, unit="LENGTH",
                                    description="0 = auto (5% of bounding-box diagonal). Increase it if a "
                                                "provided low-poly sits further from the surface")
    device: EnumProperty(name="Device", items=[("CPU", "CPU", ""), ("GPU", "GPU", "")], default="CPU")
    output_dir: StringProperty(name="Output Folder", default="", subtype="DIR_PATH",
                               description="Where to save baked textures (empty = pack into .blend)")
    image_format: EnumProperty(name="Format", items=[
        ("PNG", "PNG", ""), ("JPEG", "JPEG", ""), ("TIFF", "TIFF", ""), ("OPEN_EXR", "OpenEXR", "")],
        default="PNG")

    keep_high_poly: BoolProperty(name="Keep Combined High-Poly", default=False)
    hide_sources: BoolProperty(name="Hide Sources", default=True)

    def to_settings(self) -> core.RetopoSettings:
        d = {k: getattr(self, k) for k in core.RetopoSettings.__dataclass_fields__ if hasattr(self, k)}
        d["bake_maps"] = tuple(sorted(self.bake_maps))
        return core.RetopoSettings.from_dict(d)


PROP_NAMES = [k for k in SmartRetopoProps.__annotations__]
