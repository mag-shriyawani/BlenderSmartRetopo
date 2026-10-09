# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline step 2: optional voxel clean-up + QuadriFlow remesh."""

from __future__ import annotations

import bmesh
import bpy

from .settings import RetopoSettings, SmartRetopoError
from .utils import (
    _bbox_diagonal, _ensure_object_mode, _is_manifold, _make_active, _override, _shade_smooth,
)


def _cleanup_mesh(mesh, merge_dist: float):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def voxel_remesh(obj, resolution: int):
    size = max(obj.dimensions) / max(int(resolution), 8)
    mesh = obj.data
    mesh.remesh_voxel_size = max(size, 1e-5)
    mesh.remesh_voxel_adaptivity = 0.0
    if hasattr(mesh, "use_remesh_fix_poles"):
        mesh.use_remesh_fix_poles = True
    with _override(obj):
        bpy.ops.object.voxel_remesh()


def _quadriflow(obj, s: RetopoSettings):
    with _override(obj):
        bpy.ops.object.quadriflow_remesh(
            use_mesh_symmetry=s.use_mesh_symmetry,
            use_preserve_sharp=s.use_preserve_sharp,
            use_preserve_boundary=s.use_preserve_boundary,
            preserve_attributes=False,
            smooth_normals=False,
            mode="FACES",
            target_faces=int(s.target_faces),
            seed=int(s.seed),
        )
    if len(obj.data.polygons) == 0:
        raise SmartRetopoError("QuadriFlow produced an empty mesh.")


def retopologize(obj, s: RetopoSettings, multiple_sources: bool = False) -> bool:
    """Run QuadriFlow on ``obj`` in place. Returns True if voxel pre-remesh was used."""
    _ensure_object_mode()
    _make_active(obj)
    _cleanup_mesh(obj.data, merge_dist=_bbox_diagonal(obj) * 1e-6)

    mode = s.voxel_mode.upper()
    use_voxel = mode == "ALWAYS" or (
        mode == "AUTO" and (multiple_sources or not _is_manifold(obj.data))
    )
    if use_voxel:
        voxel_remesh(obj, s.voxel_resolution)

    try:
        _quadriflow(obj, s)
    except (RuntimeError, SmartRetopoError) as exc:
        if use_voxel or mode == "NEVER":
            raise SmartRetopoError(f"QuadriFlow failed: {exc}") from exc
        # Retry on a guaranteed-manifold voxel shell.
        voxel_remesh(obj, s.voxel_resolution)
        use_voxel = True
        _quadriflow(obj, s)

    if s.smooth_shading:
        _shade_smooth(obj.data)
    return use_voxel
