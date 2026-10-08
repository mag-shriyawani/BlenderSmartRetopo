"""Smart Retopo core pipeline.

Pure functions with no UI/registration dependencies so the pipeline can be
driven from the operator, from a headless ``blender -b`` script, or from an
MCP / Nodey bridge.

Pipeline:
    1. combine_meshes   - evaluate & merge source objects into one world-space mesh
    2. retopologize     - (optional voxel clean-up) + QuadriFlow remesh
    3. generate_uvs     - Smart UV Project / Lightmap Pack + island packing
    4. bake_textures    - Cycles selected-to-active bake of high -> low
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Optional

import bmesh
import bpy


CONVERTIBLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}

ALL_MAPS = ("BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC", "AO", "EMISSION")


# ---------------------------------------------------------------------------
# Settings / result
# ---------------------------------------------------------------------------

@dataclass
class RetopoSettings:
    name: str = ""                      # base name for outputs ("" = derive from first source)

    # Retopology
    target_faces: int = 5000
    voxel_mode: str = "AUTO"            # AUTO | ALWAYS | NEVER
    voxel_resolution: int = 256         # voxels across largest bbox dimension
    use_preserve_sharp: bool = False
    use_preserve_boundary: bool = False
    use_mesh_symmetry: bool = False
    smooth_shading: bool = True
    seed: int = 0

    # UVs
    uv_method: str = "SMART"            # SMART | LIGHTMAP
    uv_angle_limit: float = 66.0        # degrees (Smart UV)
    uv_island_margin: float = 0.005

    # Baking
    bake_maps: tuple = ("BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC")
    texture_size: int = 2048
    bake_samples: int = 16
    bake_margin: int = 16
    cage_extrusion: float = 0.0         # 0 = auto (1% of bbox diagonal)
    max_ray_distance: float = 0.0       # 0 = auto (5% of bbox diagonal)
    device: str = "CPU"                 # CPU | GPU
    output_dir: str = ""                # "" = pack images into the .blend
    image_format: str = "PNG"           # PNG | JPEG | OPEN_EXR | TIFF

    # Scene housekeeping
    keep_high_poly: bool = False
    hide_sources: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "RetopoSettings":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        if "bake_maps" in clean:
            clean["bake_maps"] = tuple(clean["bake_maps"])
        return cls(**clean)


@dataclass
class RetopoResult:
    object_name: str = ""
    material_name: str = ""
    source_objects: list = field(default_factory=list)
    source_faces: int = 0
    result_faces: int = 0
    used_voxel_remesh: bool = False
    images: dict = field(default_factory=dict)   # map -> filepath or "<packed>"
    timings: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class SmartRetopoError(RuntimeError):
    pass


ProgressFn = Optional[Callable[[str, float], None]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 1. Combine
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 2. Retopologize
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 3. UVs
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 4. Bake
# ---------------------------------------------------------------------------

# How each map is produced. "socket" maps are baked with an emission swap on
# the source materials so they capture the raw Principled input regardless of
# lighting / metallic (e.g. Cycles' DIFFUSE colour pass is black on metals).
BAKE_DEFS = {
    "BASE_COLOR": dict(socket="Base Color", colorspace="sRGB", default=(0.8, 0.8, 0.8, 1.0)),
    "ROUGHNESS": dict(socket="Roughness", colorspace="Non-Color", default=0.5),
    "METALLIC": dict(socket="Metallic", colorspace="Non-Color", default=0.0),
    "NORMAL": dict(type="NORMAL", colorspace="Non-Color"),
    "AO": dict(type="AO", colorspace="Non-Color"),
    "EMISSION": dict(type="EMIT", colorspace="sRGB"),
}

IMAGE_EXT = {"PNG": ".png", "JPEG": ".jpg", "OPEN_EXR": ".exr", "TIFF": ".tif"}


def _material_output(nt):
    outs = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"]
    for n in outs:
        if n.is_active_output and n.target in {"ALL", "CYCLES"}:
            return n
    return outs[0] if outs else None


def _find_principled(nt, out):
    if out and out.inputs["Surface"].is_linked:
        n = out.inputs["Surface"].links[0].from_node
        if n.type == "BSDF_PRINCIPLED":
            return n
    for n in nt.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


def _swap_to_emission(mat, socket_name, default):
    """Temporarily route a Principled input through an Emission shader.

    Returns a restore() callable.
    """
    nt = mat.node_tree
    out = _material_output(nt)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    surface = out.inputs["Surface"]
    orig_from = surface.links[0].from_socket if surface.is_linked else None

    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0
    bsdf = _find_principled(nt, out)
    inp = bsdf.inputs.get(socket_name) if bsdf else None

    if inp is not None and inp.is_linked:
        nt.links.new(inp.links[0].from_socket, em.inputs["Color"])
    else:
        v = inp.default_value if inp is not None else default
        if isinstance(v, float) or isinstance(v, int):
            em.inputs["Color"].default_value = (v, v, v, 1.0)
        else:
            c = tuple(v)
            em.inputs["Color"].default_value = c if len(c) == 4 else (*c[:3], 1.0)
    nt.links.new(em.outputs["Emission"], surface)

    def restore():
        nt.nodes.remove(em)
        if orig_from is not None:
            nt.links.new(orig_from, surface)

    return restore


def _ensure_source_materials(high):
    """Give empty material slots (or no slots) a default Principled material."""
    default = None

    def get_default():
        nonlocal default
        if default is None:
            default = bpy.data.materials.new("SmartRetopo_Default")
            if hasattr(default, "use_nodes"):
                default.use_nodes = True
        return default

    if not high.data.materials:
        high.data.materials.append(get_default())
    for i, m in enumerate(high.data.materials):
        if m is None:
            high.data.materials[i] = get_default()
    for m in high.data.materials:
        if hasattr(m, "use_nodes") and not m.use_nodes:
            m.use_nodes = True
    return default


def _setup_cycles(scene, s: RetopoSettings):
    saved = dict(engine=scene.render.engine)
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    saved.update(samples=cy.samples, device=cy.device)
    cy.samples = max(int(s.bake_samples), 1)
    cy.device = "CPU"
    if s.device.upper() == "GPU":
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = backend
                except TypeError:
                    continue
                prefs.refresh_devices()
                gpus = [d for d in prefs.devices if d.type == backend]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type == backend
                    cy.device = "GPU"
                    break
        except Exception:
            pass
    return saved


def _restore_cycles(scene, saved):
    scene.cycles.samples = saved["samples"]
    scene.cycles.device = saved["device"]
    scene.render.engine = saved["engine"]


def _build_target_material(low, name):
    mat = bpy.data.materials.new(name)
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    low.data.materials.clear()
    low.data.materials.append(mat)
    nt = mat.node_tree
    out = _material_output(nt) or nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = _find_principled(nt, out)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat, bsdf


def bake_textures(high, low, s: RetopoSettings, base_name: str,
                  progress: ProgressFn = None) -> tuple[bpy.types.Material, dict]:
    maps = [m for m in ALL_MAPS if m in set(s.bake_maps)]
    mat, bsdf = _build_target_material(low, f"{base_name}_baked")
    if not maps:
        return mat, {}

    nt = mat.node_tree
    _ensure_source_materials(high)
    src_mats = list({m for m in high.data.materials if m is not None})

    diag = _bbox_diagonal(high)
    extrusion = s.cage_extrusion if s.cage_extrusion > 0 else diag * 0.01
    ray_dist = s.max_ray_distance if s.max_ray_distance > 0 else diag * 0.05

    out_dir = bpy.path.abspath(s.output_dir) if s.output_dir else ""
    if out_dir and s.output_dir.startswith("//") and not bpy.data.filepath:
        out_dir = ""  # relative path but unsaved .blend -> pack instead
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    scene = bpy.context.scene
    saved = _setup_cycles(scene, s)
    _ensure_object_mode()
    high.hide_set(False)
    high.hide_render = False

    images = {}
    nodes = {}
    try:
        for i, key in enumerate(maps):
            spec = BAKE_DEFS[key]
            if progress:
                progress(f"Baking {key}", i / len(maps))

            img = bpy.data.images.new(
                f"{base_name}_{key.lower()}", s.texture_size, s.texture_size,
                alpha=False, float_buffer=(s.image_format == "OPEN_EXR"),
            )
            img.colorspace_settings.name = spec["colorspace"]
            node = nt.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.label = key
            node.location = (-700, 300 - 300 * i)
            for n in nt.nodes:
                n.select = False
            node.select = True
            nt.nodes.active = node
            nodes[key] = node

            restores = []
            if "socket" in spec:
                bake_type = "EMIT"
                for m in src_mats:
                    restores.append(_swap_to_emission(m, spec["socket"], spec["default"]))
            else:
                bake_type = spec["type"]

            _make_active(low, others=[high])
            try:
                bpy.ops.object.bake(
                    type=bake_type,
                    use_selected_to_active=True,
                    cage_extrusion=extrusion,
                    max_ray_distance=ray_dist,
                    margin=s.bake_margin,
                    use_clear=True,
                    target="IMAGE_TEXTURES",
                    save_mode="INTERNAL",
                    normal_space="TANGENT",
                )
            finally:
                for r in restores:
                    r()

            if out_dir:
                path = os.path.join(out_dir, img.name + IMAGE_EXT.get(s.image_format, ".png"))
                img.filepath_raw = path
                img.file_format = s.image_format
                img.save()
                images[key] = path
            else:
                img.pack()
                images[key] = "<packed>"
    finally:
        _restore_cycles(scene, saved)

    _wire_material(nt, bsdf, nodes)
    if progress:
        progress("Baking done", 1.0)
    return mat, images


def _wire_material(nt, bsdf, nodes):
    L = nt.links.new
    if "BASE_COLOR" in nodes:
        L(nodes["BASE_COLOR"].outputs["Color"], bsdf.inputs["Base Color"])
    if "ROUGHNESS" in nodes:
        L(nodes["ROUGHNESS"].outputs["Color"], bsdf.inputs["Roughness"])
    if "METALLIC" in nodes:
        L(nodes["METALLIC"].outputs["Color"], bsdf.inputs["Metallic"])
    if "NORMAL" in nodes:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-300, -300)
        L(nodes["NORMAL"].outputs["Color"], nm.inputs["Color"])
        L(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if "EMISSION" in nodes:
        sock = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if sock is not None:
            L(nodes["EMISSION"].outputs["Color"], sock)
            st = bsdf.inputs.get("Emission Strength")
            if st is not None:
                st.default_value = 1.0
    # AO is left as an unconnected image node (use it in a glTF Material
    # Output / game-engine occlusion slot).


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

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
        sub = (lambda l, f: step(l, 0.5 + 0.5 * f)) if progress else None
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


def _remove_object(obj):
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
