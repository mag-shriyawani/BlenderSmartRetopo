# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import bpy

from . import core
from .props import PROP_NAMES, SmartRetopoProps


class SMARTRETOPO_PG_settings(SmartRetopoProps, bpy.types.PropertyGroup):
    """Panel settings stored on the scene (scene.smart_retopo)."""


# Events that only move the view; everything else that presses a key or a
# button is swallowed while a UI run is going, so the scene can't change
# under the pipeline.
_NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM", "NDOF_MOTION",
}
_INPUT_VALUES = {"PRESS", "RELEASE", "CLICK", "DOUBLE_CLICK", "CLICK_DRAG"}
TICK_SECONDS = 0.05
# If the bake job stops without either bake handler firing, assume it finished
# after this many ticks.
BAKE_GRACE_TICKS = 20

# The UI run in progress (an OBJECT_OT_smart_retopo instance) or None. The
# panel reads it to draw the progress bar.
_active = None


def running():
    """(label, fraction) of the UI run in progress, or None."""
    return (_active._label, _active._fraction) if _active is not None else None


def _store_result(op, context, res):
    op.result_json = json.dumps(res.to_dict())
    # Last result is also stashed on the window manager for automation callers.
    context.window_manager["smart_retopo_last_result"] = op.result_json
    op.report({"INFO"}, f"Smart Retopo: {res.source_faces} -> {res.result_faces} faces "
                        f"in {res.timings.get('total', 0):.1f}s ({res.object_name})")


class OBJECT_OT_smart_retopo(SmartRetopoProps, bpy.types.Operator):
    """Combine selected objects, retopologize with QuadriFlow, unwrap and bake textures"""

    bl_idname = "object.smart_retopo"
    bl_label = "Smart Retopo"
    bl_options = {"REGISTER", "UNDO"}

    result_json: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        if _active is not None:
            cls.poll_message_set("Smart Retopo is already running")
            return False
        return any(o.type in core.CONVERTIBLE_TYPES for o in context.selected_objects)

    def _sources(self, context):
        return [o for o in context.selected_objects if o.type in core.CONVERTIBLE_TYPES]

    # -- UI: modal, redraws between steps, bakes as Blender's bake job ---------

    def invoke(self, context, event):
        # From the UI: take settings from the panel unless explicitly overridden.
        panel = context.scene.smart_retopo
        for name in PROP_NAMES:
            if not self.properties.is_property_set(name):
                setattr(self, name, getattr(panel, name))
        # The UV mode toggle is only shown with a low-poly; don't let a hidden
        # leftover EXISTING fail the run.
        if not self.low_poly_object and not self.properties.is_property_set("uv_mode"):
            self.uv_mode = "GENERATE"
        if context.window is None:
            return self.execute(context)

        self._gen = core.iter_smart_retopo(self._sources(context), self.to_settings())
        try:
            step = next(self._gen)  # validates the settings; no work done yet
        except core.SmartRetopoError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        global _active
        _active = self
        self._bake = None            # dict(done=None|"COMPLETE"|"CANCEL", idle=ticks) while baking
        self._cancel_requested = False
        self._show(context, step)
        wm = context.window_manager
        self._timer = wm.event_timer_add(TICK_SECONDS, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "TIMER":
            return self._tick(context)
        if event.type == "ESC" and event.value == "PRESS":
            # During a bake, Blender's bake job takes Esc itself and stops the
            # bake; we see that through the cancel handler. This is the fallback.
            if self._bake is None:
                return self._finish(context, cancelled=True)
            self._cancel_requested = True
            self._label = "Cancelling after the current bake..."
            self._redraw(context)
            return {"RUNNING_MODAL"}
        if event.value in _INPUT_VALUES and event.type not in _NAV_EVENTS:
            return {"RUNNING_MODAL"}  # swallow edits while running
        return {"PASS_THROUGH"}

    def cancel(self, context):
        # Blender is closing the window or loading a file.
        global _active
        try:
            self._finish(context, cancelled=True)
        except ReferenceError:  # the run's data is already gone
            _active = None

    def _tick(self, context):
        if self._bake is not None:
            outcome = self._bake_outcome()
            if outcome is None:
                return {"PASS_THROUGH"}
            self._stop_bake_watch()
            if outcome == "CANCEL" or self._cancel_requested:
                return self._finish(context, cancelled=True)
        try:
            step = next(self._gen)  # does the work announced by the previous step
        except StopIteration as stop:
            return self._finish(context, result=stop.value)
        except Exception as exc:
            return self._finish(context, error=exc)
        self._show(context, step)
        if step.bake is not None:
            return self._start_bake(context, step.bake)
        return {"PASS_THROUGH"}

    def _start_bake(self, context, kwargs):
        self._bake = dict(done=None, idle=0)
        bpy.app.handlers.object_bake_complete.append(self._on_bake_complete)
        bpy.app.handlers.object_bake_cancel.append(self._on_bake_cancel)
        try:
            started = "RUNNING_MODAL" in bpy.ops.object.bake("INVOKE_DEFAULT", **kwargs)
            err = None if started else "Bake did not start"
        except RuntimeError as exc:
            err = str(exc)
        if err is None:
            return {"PASS_THROUGH"}
        self._stop_bake_watch()
        try:
            self._gen.throw(core.SmartRetopoError(err))
        except Exception as exc:
            return self._finish(context, error=exc)
        return self._finish(context, error=core.SmartRetopoError(err))

    # Handlers only record the outcome; _tick acts on it.
    def _on_bake_complete(self, *_args):
        if self._bake is not None:
            self._bake["done"] = "COMPLETE"

    def _on_bake_cancel(self, *_args):
        if self._bake is not None:
            self._bake["done"] = "CANCEL"

    def _bake_outcome(self):
        if self._bake["done"]:
            return self._bake["done"]
        if bpy.app.is_job_running("OBJECT_BAKE"):
            self._bake["idle"] = 0
            return None
        self._bake["idle"] += 1
        return "COMPLETE" if self._bake["idle"] >= BAKE_GRACE_TICKS else None

    def _stop_bake_watch(self):
        for handlers in (bpy.app.handlers.object_bake_complete, bpy.app.handlers.object_bake_cancel):
            for h in list(handlers):
                if getattr(h, "__self__", None) is self:
                    handlers.remove(h)
        self._bake = None

    def _show(self, context, step):
        self._label, self._fraction = step.label, step.fraction
        print(f"[SmartRetopo] {step.label} ({step.fraction * 100:.0f}%)")
        self._redraw(context)

    def _redraw(self, context):
        if context.workspace is not None:
            context.workspace.status_text_set(
                f"Smart Retopo: {self._label} ({self._fraction * 100:.0f}%)    Esc to cancel")
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def _finish(self, context, result=None, error=None, cancelled=False):
        global _active
        if self._bake is not None:
            self._stop_bake_watch()
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if cancelled:
            self._gen.close()  # removes what the run created, restores the scene
        if _active is self:
            _active = None
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        if error is not None:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if cancelled:
            self.report({"WARNING"}, "Smart Retopo cancelled")
            return {"CANCELLED"}
        _store_result(self, context, result)
        return {"FINISHED"}

    # -- Python / automation: synchronous ---------------------------------------

    def execute(self, context):
        wm = context.window_manager
        has_progress = context.window is not None
        if has_progress:
            wm.progress_begin(0, 100)

        def progress(label, frac):
            print(f"[SmartRetopo] {label} ({frac * 100:.0f}%)")
            if has_progress:
                wm.progress_update(int(frac * 100))

        try:
            res = core.smart_retopo(self._sources(context), self.to_settings(), progress=progress)
        except core.SmartRetopoError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            if has_progress:
                wm.progress_end()

        _store_result(self, context, res)
        return {"FINISHED"}


classes = (SMARTRETOPO_PG_settings, OBJECT_OT_smart_retopo)
