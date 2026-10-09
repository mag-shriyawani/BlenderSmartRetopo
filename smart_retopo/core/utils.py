# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene / mesh helpers shared by the pipeline steps."""

from __future__ import annotations

import math

import bmesh
import bpy


def _ensure_object_mode():
    if bpy.context.mode != "OBJECT" and bpy.context.view_layer.objects.active:
        bpy.ops.object.mode_set(mode="OBJECT")


def _make_active(obj, others=()):
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o.select_get():
            o.select_set(False)
    for o in others:
        o.select_set(True)
    obj.select_set(True)
    vl.objects.active = obj


def _override(obj, selected=None):
    selected = list(selected) if selected else [obj]
    return bpy.context.temp_override(
        object=obj,
        active_object=obj,
        selected_objects=selected,
        selected_editable_objects=selected,
    )


def _bbox_diagonal(obj) -> float:
    d = obj.dimensions
    return max(math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z), 1e-6)


def _is_manifold(mesh) -> bool:
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        if not bm.faces:
            return False
        return all(e.is_manifold and e.is_contiguous for e in bm.edges)
    finally:
        bm.free()


def _shade_smooth(mesh):
    if hasattr(mesh, "shade_smooth"):
        mesh.shade_smooth()
    else:  # < 4.1
        for p in mesh.polygons:
            p.use_smooth = True


def _link_to_scene(obj, like=None):
    coll = None
    if like is not None and like.users_collection:
        coll = like.users_collection[0]
    (coll or bpy.context.scene.collection).objects.link(obj)


def _remove_object(obj):
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
