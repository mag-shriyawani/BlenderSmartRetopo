# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline step 1: evaluate & merge source objects into one world-space mesh."""

from __future__ import annotations

from typing import Iterable

import bpy

from .settings import CONVERTIBLE_TYPES, SmartRetopoError
from .utils import _ensure_object_mode, _link_to_scene, _override


def combine_meshes(objects: Iterable[bpy.types.Object], name: str) -> bpy.types.Object:
    """Evaluate (modifiers applied) and merge objects into one new world-space mesh object.

    Originals are left untouched. Material slots (including object-linked
    materials) are carried over.
    """
    objects = [o for o in objects if o.type in CONVERTIBLE_TYPES]
    if not objects:
        raise SmartRetopoError("No mesh-convertible objects to combine.")

    _ensure_object_mode()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    temps = []
    for src in objects:
        ev = src.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=depsgraph)
        mesh.transform(src.matrix_world)
        if src.matrix_world.is_negative:
            mesh.flip_normals()
        mesh.materials.clear()
        for slot in src.material_slots:
            mesh.materials.append(slot.material)
        tmp = bpy.data.objects.new(f"{name}_tmp", mesh)
        _link_to_scene(tmp, like=objects[0])
        temps.append(tmp)

    target = temps[0]
    if len(temps) > 1:
        with _override(target, temps):
            bpy.ops.object.join()
    target.name = name
    target.data.name = name
    return target
