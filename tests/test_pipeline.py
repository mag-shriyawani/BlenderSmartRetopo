# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end Smart Retopo test.

Run with Blender:   blender -b --factory-startup -P tests/test_pipeline.py
or the bpy module:  python tests/test_pipeline.py      (pip install bpy)

Builds a scene (subdivided checker sphere + intersecting red cube), runs the
operator, and asserts on the result. Then repeats with a provided low-poly
(existing and generated UVs) and checks the settings validation. Outputs go to
tests/_output/.
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


MAPS = {"BASE_COLOR", "NORMAL", "ROUGHNESS", "METALLIC", "AO"}


def _result():
    return json.loads(bpy.context.window_manager["smart_retopo_last_result"])


def _check_bake(res, low):
    assert len(low.data.materials) == 1
    assert set(res["images"]) == MAPS
    for p in res["images"].values():
        assert os.path.isfile(p), p
    assert not any(o.name.endswith("_high") for o in bpy.data.objects), "high-poly not cleaned up"


def test_quadriflow():
    objs = build_scene()
    for o in objs:
        o.select_set(True)
    r = bpy.ops.object.smart_retopo(
        target_faces=2000, texture_size=256, bake_samples=4,
        bake_maps=MAPS, output_dir=os.path.join(OUT, "textures"),
    )
    assert r == {"FINISHED"}, r
    res = _result()
    print(json.dumps(res, indent=1))
    # Saved so tests/ci/check_result_schema.py can validate a real result.
    with open(os.path.join(OUT, "result.json"), "w") as f:
        json.dump(res, f, indent=1)

    low = bpy.data.objects[res["object_name"]]
    assert 1000 < res["result_faces"] < 4000, res["result_faces"]
    assert res["low_poly_object"] == "" and res["uvs_generated"] is True
    assert [u.name for u in low.data.uv_layers] == ["UVMap"]
    _check_bake(res, low)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "result.blend"))


def build_low_poly_scene():
    """The checker sphere as the only source, plus a hand-made UV'd low-poly sphere."""
    sph, cube = build_scene()
    bpy.data.objects.remove(cube, do_unlink=True)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=16, ring_count=8, calc_uvs=True)
    lp = bpy.context.object
    lp.name = "LowPoly"
    render_uv = lp.data.uv_layers[0]
    render_uv.name = "Bake"
    # A second, active-for-editing map: the bake must still use the render map.
    extra = lp.data.uv_layers.new(name="Extra")
    lp.data.uv_layers.active = extra
    render_uv.active_render = True
    return sph, lp


def _uvs(mesh, name):
    co = [0.0] * (2 * len(mesh.loops))
    mesh.uv_layers[name].uv.foreach_get("vector", co)
    return co


def test_provided_low_poly(uv_mode):
    sph, lp = build_low_poly_scene()
    orig_uvs = _uvs(lp.data, "Bake")
    orig_mesh = lp.data.name
    for o in (sph, lp):  # selecting the low-poly too must not make it a source
        o.select_set(True)
    r = bpy.ops.object.smart_retopo(
        low_poly_object="LowPoly", uv_mode=uv_mode, texture_size=256, bake_samples=4,
        bake_maps=MAPS, output_dir=os.path.join(OUT, f"textures_{uv_mode.lower()}"),
    )
    assert r == {"FINISHED"}, r
    res = _result()
    print(json.dumps(res, indent=1))

    low = bpy.data.objects[res["object_name"]]
    assert low is not lp
    assert res["source_objects"] == [sph.name], res["source_objects"]
    assert res["low_poly_object"] == "LowPoly"
    assert res["used_voxel_remesh"] is False
    assert res["result_faces"] == 16 * 8 == len(low.data.polygons), res["result_faces"]
    if uv_mode == "EXISTING":
        assert res["uvs_generated"] is False
        assert low.data.uv_layers.active.name == "Bake"
        assert _uvs(low.data, "Bake") == orig_uvs, "existing UVs changed"
        assert res["warnings"] == [], res["warnings"]
        with open(os.path.join(OUT, "result_low_poly.json"), "w") as f:
            json.dump(res, f, indent=1)
    else:
        assert res["uvs_generated"] is True
        assert [u.name for u in low.data.uv_layers] == ["UVMap"]
    _check_bake(res, low)

    # The user's low-poly is untouched (just hidden, like the sources).
    assert lp.data.name == orig_mesh
    assert [u.name for u in lp.data.uv_layers] == ["Bake", "Extra"]
    assert _uvs(lp.data, "Bake") == orig_uvs
    assert lp.hide_get()


def test_invalid_settings():
    sph, lp = build_low_poly_scene()
    lp.data.uv_layers.remove(lp.data.uv_layers["Bake"])
    lp.data.uv_layers.remove(lp.data.uv_layers["Extra"])
    n_objects = len(bpy.data.objects)
    cases = [
        (dict(uv_mode="EXISTING"), "needs a low-poly"),
        (dict(low_poly_object="Missing"), "not found"),
        (dict(low_poly_object="LowPoly", uv_mode="EXISTING"), "has no UV map"),
    ]
    for settings, msg in cases:
        try:
            smart_retopo.core.smart_retopo([sph, lp], dict(settings, texture_size=64))
        except smart_retopo.core.SmartRetopoError as exc:
            assert msg in str(exc), (settings, exc)
        else:
            raise AssertionError(f"no error for {settings}")
        assert len(bpy.data.objects) == n_objects, "failed run left objects behind"


# A provided low-poly skips QuadriFlow (~8 s), which these tests don't need.
STEP_SETTINGS = dict(low_poly_object="LowPoly", texture_size=64, bake_samples=1,
                     bake_maps=["BASE_COLOR", "NORMAL", "METALLIC"])


def _drive(gen, stop_at_bake=None, inject=None):
    """Drive a step generator like the modal operator does.

    Runs each requested bake synchronously. At the ``stop_at_bake``-th bake
    request (0-based), closes the generator (``inject=None``, a cancel) or
    throws ``inject`` into it (a failed bake job). Returns (steps, result).
    """
    steps, bakes = [], 0
    step = next(gen)
    try:
        while True:
            steps.append(step)
            if step.bake is not None:
                if bakes == stop_at_bake:
                    if inject is None:
                        gen.close()
                        return steps, None
                    gen.throw(inject)
                bpy.ops.object.bake(**step.bake)
                bakes += 1
            step = next(gen)
    except StopIteration as stop:
        return steps, stop.value


def test_steps():
    """The step generator reports ordered progress and hands each bake to the caller."""
    objs = build_low_poly_scene()
    steps, res = _drive(smart_retopo.core.iter_smart_retopo(objs, STEP_SETTINGS))
    fracs = [s.fraction for s in steps]
    assert fracs == sorted(fracs) and fracs[0] == 0.0, fracs
    assert (steps[-1].label, steps[-1].fraction) == ("Done", 1.0), steps[-1]
    baked = [s.label for s in steps if s.bake is not None]
    assert baked == ["Baking BASE_COLOR (1/3)", "Baking NORMAL (2/3)", "Baking METALLIC (3/3)"], baked
    assert isinstance(res, smart_retopo.core.RetopoResult)
    assert set(res.images) == set(STEP_SETTINGS["bake_maps"])
    assert res.object_name in bpy.data.objects


def _assert_clean_after_abort(objs, before):
    names = {o.name for o in bpy.data.objects}
    assert names == before["objects"], names ^ before["objects"]
    assert {m.name for m in bpy.data.materials} == before["materials"], "baked material left"
    assert {i.name for i in bpy.data.images} == before["images"], "baked images left"
    for m in bpy.data.materials:
        assert not any(n.type == "EMISSION" for n in m.node_tree.nodes), f"emission swap left in {m.name}"
    assert not any(o.hide_get() or o.hide_render for o in objs), "sources left hidden"
    assert bpy.context.scene.render.engine == before["engine"], "render engine not restored"


def test_abort():
    """Cancelling (close) or a failed bake (throw) mid-run leaves the scene as it was."""
    for stop_at_bake, inject in ((0, None), (1, None), (1, RuntimeError("bake job failed"))):
        objs = build_low_poly_scene()
        before = dict(objects={o.name for o in bpy.data.objects},
                      materials={m.name for m in bpy.data.materials},
                      images={i.name for i in bpy.data.images},
                      engine=bpy.context.scene.render.engine)
        gen = smart_retopo.core.iter_smart_retopo(objs, STEP_SETTINGS)
        try:
            _, res = _drive(gen, stop_at_bake=stop_at_bake, inject=inject)
        except RuntimeError as exc:
            assert inject is not None and exc is inject, exc
        else:
            assert inject is None and res is None
        _assert_clean_after_abort(objs, before)


def main():
    smart_retopo.register()
    try:
        test_steps()
        test_abort()
        test_quadriflow()
        test_provided_low_poly("EXISTING")
        test_provided_low_poly("GENERATE")
        test_invalid_settings()
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
