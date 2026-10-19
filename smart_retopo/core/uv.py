# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline step 3: Smart UV Project / Lightmap Pack + island packing, or keep existing UVs."""

from __future__ import annotations

import math

import bpy

from .settings import RetopoSettings, SmartRetopoError
from .utils import _ensure_object_mode, _make_active


def use_existing_uvs(obj) -> list[str]:
    """Bake into the object's existing UVs. Returns warnings.

    The render UV map (the one exporters and Cycles use) becomes the active
    layer, which is the one the bake writes through. Other layers are kept.
    """
    mesh = obj.data
    if not mesh.uv_layers:
        raise SmartRetopoError(
            f"Low-poly '{obj.name}' has no UV map. Unwrap it, or set UVs to Generate."
        )
    layer = next((u for u in mesh.uv_layers if u.active_render), mesh.uv_layers[0])
    mesh.uv_layers.active = layer

    warnings = []
    n = len(mesh.loops)
    if n:
        co = [0.0] * (2 * n)
        layer.uv.foreach_get("vector", co)
        eps = 1e-4
        if min(co) < -eps or max(co) > 1.0 + eps:
            warnings.append(
                f"UV map '{layer.name}' extends outside 0-1; those parts share texels with "
                "other islands and bake incorrectly."
            )
    return warnings


def generate_uvs(obj, s: RetopoSettings):
    mesh = obj.data
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    uv = mesh.uv_layers.new(name="UVMap")
    mesh.uv_layers.active = uv

    _ensure_object_mode()
    _make_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        if s.uv_method.upper() == "LIGHTMAP":
            bpy.ops.uv.lightmap_pack(PREF_CONTEXT="ALL_FACES", PREF_MARGIN_DIV=0.2)
        else:
            bpy.ops.uv.smart_project(
                angle_limit=math.radians(s.uv_angle_limit),
                island_margin=s.uv_island_margin,
            )
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.pack_islands(rotate=True, margin=s.uv_island_margin)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
