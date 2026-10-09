"""Smart Retopo - combine, QuadriFlow retopologize, UV unwrap and Cycles-bake meshes.

Automation:
    bpy.ops.object.smart_retopo(target_faces=3000, bake_maps={'BASE_COLOR', 'NORMAL'})
    json.loads(bpy.context.window_manager["smart_retopo_last_result"])

or headless:
    blender -b -P smart_retopo/cli.py -- --input in.glb --output out.glb --faces 3000
"""

if "bpy" in locals():
    import importlib
    from . import core, props, operators, ui
    for m in (core, props, operators, ui):
        importlib.reload(m)
else:
    from . import core, props, operators, ui

import bpy

_classes = operators.classes + ui.classes


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.smart_retopo = bpy.props.PointerProperty(type=operators.SMARTRETOPO_PG_settings)
    bpy.types.VIEW3D_MT_object.append(ui.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(ui.menu_func)
    del bpy.types.Scene.smart_retopo
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
