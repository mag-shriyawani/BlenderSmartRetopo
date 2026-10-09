# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Full pipeline: combine -> QuadriFlow -> UV -> bake."""

from __future__ import annotations

import time
from typing import Iterable

import bpy

from .bake import bake_textures
from .combine import combine_meshes
from .retopo import retopologize
from .settings import (
    CONVERTIBLE_TYPES, ProgressFn, RetopoResult, RetopoSettings, SmartRetopoError,
)
from .utils import _link_to_scene, _make_active, _remove_object
from .uv import generate_uvs


def smart_retopo(objects: Iterable[bpy.types.Object],
                 settings: RetopoSettings | dict | None = None,
                 progress: ProgressFn = None) -> RetopoResult:
    """Run combine -> QuadriFlow -> UV -> bake. Returns a RetopoResult."""
    if settings is None:
        s = RetopoSettings()
    elif isinstance(settings, dict):
        s = RetopoSettings.from_dict(settings)
    else:
        s = settings

    sources = [o for o in objects if o.type in CONVERTIBLE_TYPES]
    if not sources:
        raise SmartRetopoError("Select at least one mesh object.")

    res = RetopoResult(source_objects=[o.name for o in sources])
    base = s.name or (sources[0].name if len(sources) == 1 else f"{sources[0].name}_combined")
    t0 = time.perf_counter()

    def step(label, frac):
        if progress:
            progress(label, frac)

    # 1. Combine
    step("Combining meshes", 0.0)
    high = combine_meshes(sources, f"{base}_high")
    res.source_faces = len(high.data.polygons)
    res.timings["combine"] = time.perf_counter() - t0

    low = None
    try:
        # 2. Retopo (on a copy so the high-poly survives for baking)
        t = time.perf_counter()
        step("Retopologizing (QuadriFlow)", 0.1)
        low = high.copy()
        low.data = high.data.copy()
        low.name = low.data.name = f"{base}_retopo"
        _link_to_scene(low, like=high)
        res.used_voxel_remesh = retopologize(low, s, multiple_sources=len(sources) > 1)
        res.result_faces = len(low.data.polygons)
        res.timings["retopo"] = time.perf_counter() - t

        # 3. UVs
        t = time.perf_counter()
        step("Generating UVs", 0.4)
        generate_uvs(low, s)
        res.timings["uv"] = time.perf_counter() - t

        # 4. Bake
        t = time.perf_counter()
        step("Baking textures (Cycles)", 0.5)
        sub = (lambda label, f: step(label, 0.5 + 0.5 * f)) if progress else None
        # Originals coincide with the combined high-poly and would occlude AO.
        vis = [(o, o.hide_get(), o.hide_render) for o in sources]
        for o in sources:
            o.hide_set(True)
            o.hide_render = True
        try:
            mat, images = bake_textures(high, low, s, base, progress=sub)
        finally:
            for o, h, hr in vis:
                o.hide_set(h)
                o.hide_render = hr
        res.material_name = mat.name
        res.images = images
        res.timings["bake"] = time.perf_counter() - t
    except Exception:
        if low is not None:
            _remove_object(low)
        _remove_object(high)
        raise

    # Housekeeping
    if s.keep_high_poly:
        high.hide_set(True)
        high.hide_render = True
    else:
        _remove_object(high)
    if s.hide_sources:
        for o in sources:
            o.hide_set(True)
            o.hide_render = True

    _make_active(low)
    res.object_name = low.name
    res.timings["total"] = time.perf_counter() - t0
    step("Done", 1.0)
    return res
