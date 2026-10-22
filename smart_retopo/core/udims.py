# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline proposed step: UDIM setup """

#import math
import bpy
import bmesh
from bpy_extras.bmesh_utils import bmesh_linked_uv_islands

from .settings import RetopoSettings, SmartRetopoError
from .utils import _ensure_object_mode, _make_active
#from .uv import generate_uvs

def _tile_offset(i):
    """i-th tile -> (u, v) offset in UV space. 10 tiles per row."""
    return i % 10, i // 10

def _udim_number(i):
    return 1001 + (i % 10) + 10 * (i // 10)

def arrange_islands(islands, numTiles):
    """ Take existing uv islands and sort them into udim groups """

    sizes = [sum(f.calc_area() for f in island) for island in islands]
    #indices of islands from biggest to smallest
    order = sorted(range(len(islands)), key = lambda i: sizes[i], reverse=True)
    remaining_area = sum(sizes)
    remaining_tiles = numTiles
    udim_groups = [[] for _ in range(numTiles)]
    counter = 0
    """ Setting up solo tiles for dominant islands """
    for i in order:

        if remaining_tiles > 1:
            fair_share = remaining_area / remaining_tiles
        else:
            break

        if sizes[i] > fair_share:
            udim_groups[counter].append(i)
            remaining_area -= sizes[i]
            remaining_tiles -= 1
            counter += 1
        else:
            break

    """ Setting up group tiles for remaining islands """
    load = [0.0] * remaining_tiles    # surface area covered by islands in each tile
    for i in order[counter:]:
        t = load.index(min(load))
        udim_groups[counter + t].append(i)
        load[t] += sizes[i]

    return udim_groups


def unwrap_groups(mesh, islands, udim_groups, margin=0.0):
    """
    Pack each group of islands into 0-1, then move it to its UDIM tile.
    Expects Edit Mode with UV sync selection off.
    """
    ts = bpy.context.tool_settings
    select_mode = tuple(ts.mesh_select_mode)

    # Read face indices now: `islands` holds BMFaces that go stale once an operator runs
    face_groups = [[f.index for i in group for f in islands[i]] for group in udim_groups]

    # Face select mode, so selecting a group can't spill onto neighbouring faces
    ts.mesh_select_mode = (False, False, True)
    try:

        for tile_index, face_ids in enumerate(face_groups):
            # Select only this group's faces
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()

            if not face_ids:
                continue

            for fi in face_ids:
                bm.faces[fi].select_set(True)
            bmesh.update_edit_mesh(mesh)

            # Pack them into 0-1
            bpy.ops.uv.select_all(action="SELECT")
            bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, margin=margin)

            # Move them into their tile (tile 0 is already in place)
            du, dv = _tile_offset(tile_index)
            if du or dv:
                bm = bmesh.from_edit_mesh(mesh)
                bm.faces.ensure_lookup_table()
                uv = bm.loops.layers.uv.active
                for fi in face_ids:
                    for loop in bm.faces[fi].loops:
                        loop[uv].uv.x += du
                        loop[uv].uv.y += dv
                bmesh.update_edit_mesh(mesh)
    finally:
        ts.mesh_select_mode = select_mode


def setup_udims(obj, s: RetopoSettings):
    mesh = obj.data

    _ensure_object_mode()
    _make_active(obj)
    ts = bpy.context.tool_settings
    sync = ts.use_uv_select_sync

    """ Setting up UDIM Tiles """
    if not mesh.uv_layers:
        raise SmartRetopoError(
            f"'{obj.name}' has no UV map. Unwrap it."
        )

    try:
        ts.use_uv_select_sync = False

        #layer = next((u for u in mesh.uv_layers if u.active_render), mesh.uv_layers[0])
        #mesh.uv_layers.active = layer

        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)

        uv_layer = bm.loops.layers.uv.active
        islands = bmesh_linked_uv_islands(bm, uv_layer)

        udim_groups = arrange_islands(islands, s.target_udims)

        unwrap_groups(mesh, islands, udim_groups, margin = s.uv_island_margin)

    finally:
        ts.use_uv_select_sync = sync
        if obj.mode == "EDIT":
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.object.mode_set(mode="OBJECT")

    return {_udim_number(t): len(g) for t, g in enumerate(udim_groups) if g}
