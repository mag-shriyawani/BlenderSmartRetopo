# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline step 3: Smart UV Project / Lightmap Pack + island packing."""

from __future__ import annotations

import math

import bpy

from .settings import RetopoSettings
from .utils import _ensure_object_mode, _make_active


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
