# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import bpy

from . import core
from .props import PROP_NAMES, SmartRetopoProps


class SMARTRETOPO_PG_settings(SmartRetopoProps, bpy.types.PropertyGroup):
    """Panel settings stored on the scene (scene.smart_retopo)."""


class OBJECT_OT_smart_retopo(SmartRetopoProps, bpy.types.Operator):
    """Combine selected objects, retopologize with QuadriFlow, unwrap and bake textures"""

    bl_idname = "object.smart_retopo"
    bl_label = "Smart Retopo"
    bl_options = {"REGISTER", "UNDO"}

    result_json: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return any(o.type in core.CONVERTIBLE_TYPES for o in context.selected_objects)

    def invoke(self, context, event):
        # From the UI: take settings from the panel unless explicitly overridden.
        panel = context.scene.smart_retopo
        for name in PROP_NAMES:
            if not self.properties.is_property_set(name):
                setattr(self, name, getattr(panel, name))
        return self.execute(context)

    def execute(self, context):
        sources = [o for o in context.selected_objects if o.type in core.CONVERTIBLE_TYPES]
        wm = context.window_manager
        has_progress = context.window is not None
        if has_progress:
            wm.progress_begin(0, 100)

        def progress(label, frac):
            print(f"[SmartRetopo] {label} ({frac * 100:.0f}%)")
            if has_progress:
                wm.progress_update(int(frac * 100))

        try:
            res = core.smart_retopo(sources, self.to_settings(), progress=progress)
        except core.SmartRetopoError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            if has_progress:
                wm.progress_end()

        self.result_json = json.dumps(res.to_dict())
        # Last result is also stashed on the window manager for automation callers.
        wm["smart_retopo_last_result"] = self.result_json
        self.report({"INFO"}, f"Smart Retopo: {res.source_faces} -> {res.result_faces} faces "
                              f"in {res.timings.get('total', 0):.1f}s ({res.object_name})")
        return {"FINISHED"}


classes = (SMARTRETOPO_PG_settings, OBJECT_OT_smart_retopo)
