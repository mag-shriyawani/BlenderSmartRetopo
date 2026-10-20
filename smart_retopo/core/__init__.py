# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Smart Retopo core pipeline.

Pure functions with no UI/registration dependencies so the pipeline can be
driven from the operator, from a headless ``blender -b`` script, or from an
MCP / Nodey bridge.

Pipeline (one module per step):
    1. combine.py  - evaluate & merge source objects into one world-space mesh
    2. retopo.py   - (optional voxel clean-up) + QuadriFlow remesh
    3. uv.py       - Smart UV Project / Lightmap Pack + island packing
    4. bake.py     - Cycles selected-to-active bake of high -> low
    pipeline.py    - smart_retopo(): runs all of the above; iter_smart_retopo()
                     yields the same work as resumable steps (UI progress / cancel)
"""

if "bpy" in locals():
    import importlib
    from . import settings, utils, combine, retopo, uv, bake, pipeline
    for _m in (settings, utils, combine, retopo, uv, bake, pipeline):
        importlib.reload(_m)

import bpy  # noqa: E402,F401  (kept for the reload check above)

from .settings import (  # noqa: E402,F401
    ALL_MAPS, CONVERTIBLE_TYPES, GPU_BACKENDS, ProgressFn, RetopoResult, RetopoSettings, SmartRetopoError, Step,
)
from .combine import combine_meshes  # noqa: E402,F401
from .utils import run_steps  # noqa: E402,F401
from .retopo import retopologize, voxel_remesh  # noqa: E402,F401
from .uv import generate_uvs  # noqa: E402,F401
from .bake import BAKE_DEFS, IMAGE_EXT, bake_textures, iter_bake_textures  # noqa: E402,F401
from .pipeline import iter_smart_retopo, smart_retopo  # noqa: E402,F401
