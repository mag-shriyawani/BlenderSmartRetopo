# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless Smart Retopo runner.

    blender -b -P smart_retopo/cli.py -- --input model.glb --output model_low.glb \
        --faces 4000 --size 2048 --maps BASE_COLOR NORMAL ROUGHNESS METALLIC

Bring your own low-poly instead of QuadriFlow, keeping its UVs:

    blender -b -P smart_retopo/cli.py -- -i model.glb -o model_low.glb \
        --low-poly-file model_lod2.glb --uv-mode EXISTING

Works whether or not the add-on is installed (it imports the package from
next to this file). Prints a single line prefixed with ``SMART_RETOPO_RESULT:``
containing a JSON result, and optionally writes it to --report.

Supported inputs: .blend .glb .gltf .fbx .obj .ply .stl .usd/.usda/.usdc/.usdz
Supported outputs: .glb .gltf .fbx .obj .usd* .blend
"""

import argparse
import json
import os
import sys
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from smart_retopo import core  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="smart_retopo")
    p.add_argument("--input", "-i", required=True)
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--objects", nargs="*", help="Object names to process (default: all meshes)")
    lp = p.add_mutually_exclusive_group()
    lp.add_argument("--low-poly", default="", metavar="NAME",
                    help="Object in the input file to use as the low-poly (skips QuadriFlow)")
    lp.add_argument("--low-poly-file", default="", metavar="PATH",
                    help="Mesh file to use as the low-poly (skips QuadriFlow); its meshes are joined")
    p.add_argument("--uv-mode", choices=["GENERATE", "EXISTING"], default="GENERATE",
                   help="EXISTING keeps the low-poly's UV map (needs --low-poly or --low-poly-file)")
    p.add_argument("--faces", type=int, default=5000)
    p.add_argument("--voxel", choices=["AUTO", "ALWAYS", "NEVER"], default="AUTO")
    p.add_argument("--voxel-resolution", type=int, default=256)
    p.add_argument("--preserve-sharp", action="store_true")
    p.add_argument("--preserve-boundary", action="store_true")
    p.add_argument("--symmetry", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--uv", choices=["SMART", "LIGHTMAP"], default="SMART")
    p.add_argument("--uv-margin", type=float, default=0.005)
    p.add_argument("--maps", nargs="*", default=["BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC"],
                   choices=list(core.ALL_MAPS))
    p.add_argument("--size", type=int, default=2048)
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--margin", type=int, default=16)
    p.add_argument("--extrusion", type=float, default=0.0)
    p.add_argument("--ray-distance", type=float, default=0.0)
    p.add_argument("--device", choices=["CPU", "GPU"], default="CPU")
    p.add_argument("--texture-dir", default="", help="Default: <output dir>/<output name>_textures")
    p.add_argument("--image-format", choices=["PNG", "JPEG", "TIFF", "OPEN_EXR"], default="PNG")
    p.add_argument("--name", default="")
    p.add_argument("--report", default="", help="Write JSON result to this path")
    p.add_argument("--settings-json", default="", help="JSON file/string merged over CLI settings")
    return p.parse_args(argv)


def import_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _import(path, ext)


def _import(path, ext):
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    else:
        raise core.SmartRetopoError(f"Unsupported input format: {ext}")


def import_low_poly(path):
    """Add a low-poly file to the current scene. Returns the name of one mesh object."""
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
    else:
        _import(path, ext)
    meshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not meshes:
        raise core.SmartRetopoError(f"No mesh objects in low-poly file {path}")
    for o in bpy.data.objects:
        if o not in before:
            o.select_set(False)
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=meshes[0], selected_objects=meshes,
                                       selected_editable_objects=meshes):
            bpy.ops.object.join()
    meshes[0].name = "SmartRetopo_LowPoly"
    return meshes[0].name


def export_file(path, obj):
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if ext in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True,
                                  export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE")
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, path_mode="COPY", embed_textures=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, path_mode="COPY")
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        bpy.ops.wm.usd_export(filepath=path, selected_objects_only=True)
    elif ext == ".blend":
        bpy.ops.wm.save_as_mainfile(filepath=path)
    else:
        raise core.SmartRetopoError(f"Unsupported output format: {ext}")


def main():
    a = parse_args()
    out = os.path.abspath(a.output)
    tex_dir = a.texture_dir or os.path.join(os.path.dirname(out),
                                            os.path.splitext(os.path.basename(out))[0] + "_textures")
    settings = dict(
        name=a.name, low_poly_object=a.low_poly, uv_mode=a.uv_mode,
        target_faces=a.faces, voxel_mode=a.voxel, voxel_resolution=a.voxel_resolution,
        use_preserve_sharp=a.preserve_sharp, use_preserve_boundary=a.preserve_boundary,
        use_mesh_symmetry=a.symmetry, seed=a.seed, uv_method=a.uv, uv_island_margin=a.uv_margin,
        bake_maps=tuple(a.maps), texture_size=a.size, bake_samples=a.samples, bake_margin=a.margin,
        cage_extrusion=a.extrusion, max_ray_distance=a.ray_distance, device=a.device,
        output_dir=os.path.abspath(tex_dir), image_format=a.image_format,
    )
    if a.settings_json:
        raw = open(a.settings_json).read() if os.path.isfile(a.settings_json) else a.settings_json
        settings.update(json.loads(raw))

    report = {"ok": False}
    try:
        import_file(os.path.abspath(a.input))
        scene_objs = bpy.context.scene.objects
        if a.objects:
            objs = [scene_objs[n] for n in a.objects if n in scene_objs]
        else:
            objs = [o for o in scene_objs if o.type in core.CONVERTIBLE_TYPES and o.visible_get()]
        if a.low_poly_file:
            settings["low_poly_object"] = import_low_poly(os.path.abspath(a.low_poly_file))
        res = core.smart_retopo(objs, settings,
                                progress=lambda label, f: print(f"[SmartRetopo] {label} ({f * 100:.0f}%)", flush=True))
        export_file(out, bpy.data.objects[res.object_name])
        report = {"ok": True, "output": out, **res.to_dict()}
    except Exception as exc:
        traceback.print_exc()
        report = {"ok": False, "error": str(exc)}

    line = json.dumps(report)
    print("SMART_RETOPO_RESULT: " + line, flush=True)
    if a.report:
        with open(a.report, "w") as f:
            f.write(line)
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
