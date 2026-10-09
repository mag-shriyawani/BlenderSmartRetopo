# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end Smart Retopo test.

Run with Blender:   blender -b --factory-startup -P tests/test_pipeline.py
or the bpy module:  python tests/test_pipeline.py      (pip install bpy)

Builds a scene (subdivided checker sphere + intersecting red cube), runs the
operator, and asserts on the result. Outputs go to tests/_output/.
"""

import json
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "_output")
sys.path.insert(0, ROOT)

import smart_retopo  # noqa: E402


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=48, ring_count=24)
    sph = bpy.context.object
    m = bpy.data.materials.new("Checker")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 8
    nt.links.new(chk.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(chk.outputs["Fac"], bsdf.inputs["Metallic"])
    bsdf.inputs["Roughness"].default_value = 0.3
    sph.data.materials.append(m)
    bpy.ops.object.modifier_add(type="SUBSURF")

    bpy.ops.mesh.primitive_cube_add(size=1.2, location=(0.9, 0, 0))
    cube = bpy.context.object
    m2 = bpy.data.materials.new("Red")
    m2.use_nodes = True
    m2.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.8, 0.05, 0.05, 1)
    cube.data.materials.append(m2)
    return [sph, cube]


def main():
    smart_retopo.register()
    try:
        objs = build_scene()
        for o in objs:
            o.select_set(True)
        r = bpy.ops.object.smart_retopo(
            target_faces=2000, texture_size=256, bake_samples=4,
            bake_maps={"BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC", "AO"},
            output_dir=os.path.join(OUT, "textures"),
        )
        assert r == {"FINISHED"}, r
        res = json.loads(bpy.context.window_manager["smart_retopo_last_result"])
        print(json.dumps(res, indent=1))

        low = bpy.data.objects[res["object_name"]]
        assert 1000 < res["result_faces"] < 4000, res["result_faces"]
        assert [u.name for u in low.data.uv_layers] == ["UVMap"]
        assert len(low.data.materials) == 1
        assert set(res["images"]) == {"BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC", "AO"}
        for p in res["images"].values():
            assert os.path.isfile(p), p
        assert not any(o.name.endswith("_high") for o in bpy.data.objects), "high-poly not cleaned up"

        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "result.blend"))
        print("SMART_RETOPO_TEST: PASS")
    finally:
        smart_retopo.unregister()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("SMART_RETOPO_TEST: FAIL")
        sys.exit(1)
