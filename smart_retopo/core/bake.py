# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pipeline step 4: Cycles selected-to-active bake of high -> low."""

from __future__ import annotations

import os

import bpy

from .settings import ALL_MAPS, ProgressFn, RetopoSettings, Step
from .utils import _bbox_diagonal, _ensure_object_mode, _make_active, run_steps


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
    """Bake every map synchronously. Returns (material, {map: path | "<packed>"})."""
    return run_steps(iter_bake_textures(high, low, s, base_name), progress)


def iter_bake_textures(high, low, s: RetopoSettings, base_name: str,
                       fraction=lambda f: f):
    """Step generator for the bake (see ``Step``). Yields one bake request per map.

    ``fraction`` maps this step's own progress (0..1) onto the caller's scale.
    Returns (material, images). On failure or cancel the new material and
    images are removed, and source materials and Cycles settings restored.
    """
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
    created = []
    try:
        for i, key in enumerate(maps):
            spec = BAKE_DEFS[key]
            img = bpy.data.images.new(
                f"{base_name}_{key.lower()}", s.texture_size, s.texture_size,
                alpha=False, float_buffer=(s.image_format == "OPEN_EXR"),
            )
            created.append(img)
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
                # The caller runs the bake (blocking, or as a job) and resumes us.
                yield Step(f"Baking {key} ({i + 1}/{len(maps)})", fraction(i / len(maps)), bake=dict(
                    type=bake_type,
                    use_selected_to_active=True,
                    cage_extrusion=extrusion,
                    max_ray_distance=ray_dist,
                    margin=s.bake_margin,
                    use_clear=True,
                    target="IMAGE_TEXTURES",
                    save_mode="INTERNAL",
                    normal_space="TANGENT",
                ))
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
    except BaseException:  # includes GeneratorExit (cancel)
        low.data.materials.clear()
        bpy.data.materials.remove(mat)
        for img in created:
            bpy.data.images.remove(img)
        raise
    finally:
        _restore_cycles(scene, saved)

    _wire_material(nt, bsdf, nodes)
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
