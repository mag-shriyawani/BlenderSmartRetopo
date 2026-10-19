# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Full pipeline: combine -> QuadriFlow (or a provided low-poly) -> UV -> bake."""

from __future__ import annotations

import time
from typing import Iterable

import bpy

from .bake import bake_textures
from .combine import combine_meshes
from .retopo import retopologize
from .settings import (
    CONVERTIBLE_TYPES, UV_MODES, ProgressFn, RetopoResult, RetopoSettings, SmartRetopoError,
)
from .utils import _link_to_scene, _make_active, _remove_object
from .uv import generate_uvs, use_existing_uvs


def _resolve_low_poly(s: RetopoSettings):
    """Validate the low-poly / UV settings. Returns the provided low-poly object or None."""
    uv_mode = s.uv_mode.upper()
    if uv_mode not in UV_MODES:
        raise SmartRetopoError(f"Unknown uv_mode {s.uv_mode!r}; expected one of {', '.join(UV_MODES)}.")
    if not s.low_poly_object:
        if uv_mode == "EXISTING":
            raise SmartRetopoError("uv_mode EXISTING needs a low-poly object (low_poly_object).")
        return None
    lp = bpy.data.objects.get(s.low_poly_object)
    if lp is None:
        raise SmartRetopoError(f"Low-poly object '{s.low_poly_object}' not found.")
    if lp.type not in CONVERTIBLE_TYPES:
        raise SmartRetopoError(f"Low-poly object '{lp.name}' is a {lp.type}, not a mesh.")
    return lp


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

    low_poly = _resolve_low_poly(s)
    # The low-poly may be part of the selection; it is never a bake source.
    sources = [o for o in objects if o.type in CONVERTIBLE_TYPES and o != low_poly]
    if not sources:
        raise SmartRetopoError("Select at least one mesh object"
                               + (" besides the low-poly." if low_poly else "."))

    res = RetopoResult(source_objects=[o.name for o in sources],
                       low_poly_object=low_poly.name if low_poly else "",
                       uvs_generated=s.uv_mode.upper() == "GENERATE")
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
        # 2. Retopo (on a copy so the high-poly survives for baking), or take
        #    an evaluated, world-space copy of the provided low-poly. The
        #    user's low-poly object itself is never modified.
        t = time.perf_counter()
        if low_poly is not None:
            step("Copying provided low-poly", 0.1)
            low = combine_meshes([low_poly], f"{base}_retopo")
        else:
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
        if res.uvs_generated:
            step("Generating UVs", 0.4)
            generate_uvs(low, s)
        else:
            step("Using existing UVs", 0.4)
            res.warnings += use_existing_uvs(low)
        res.timings["uv"] = time.perf_counter() - t

        # 4. Bake
        t = time.perf_counter()
        step("Baking textures (Cycles)", 0.5)
        sub = (lambda label, f: step(label, 0.5 + 0.5 * f)) if progress else None
        # Originals coincide with the combined high-poly / the low-poly copy
        # and would occlude AO.
        originals = sources + ([low_poly] if low_poly else [])
        vis = [(o, o.hide_get(), o.hide_render) for o in originals]
        for o in originals:
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
        for o in originals:
            o.hide_set(True)
            o.hide_render = True

    _make_active(low)
    res.object_name = low.name
    res.timings["total"] = time.perf_counter() - t0
    step("Done", 1.0)
    return res
