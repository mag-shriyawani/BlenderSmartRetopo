# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy


class VIEW3D_PT_smart_retopo(bpy.types.Panel):
    bl_label = "Smart Retopo"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smart Retopo"

    def draw(self, context):
        s = context.scene.smart_retopo
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        n = len([o for o in context.selected_objects if o.type == "MESH"])
        layout.label(text=f"{n} mesh object(s) selected", icon="OBJECT_DATA")
        layout.prop(s, "name")

        box = layout.box()
        box.label(text="Retopology", icon="MOD_REMESH")
        box.prop(s, "target_faces")
        box.prop(s, "voxel_mode")
        if s.voxel_mode != "NEVER":
            box.prop(s, "voxel_resolution")
        col = box.column(heading="Options")
        col.prop(s, "use_preserve_sharp")
        col.prop(s, "use_preserve_boundary")
        col.prop(s, "use_mesh_symmetry")
        col.prop(s, "smooth_shading")
        box.prop(s, "seed")

        box = layout.box()
        box.label(text="UVs", icon="UV")
        box.prop(s, "uv_method")
        if s.uv_method == "SMART":
            box.prop(s, "uv_angle_limit")
        box.prop(s, "uv_island_margin")

        box = layout.box()
        box.label(text="Bake (Cycles)", icon="RENDER_STILL")
        col = box.column(align=True)
        col.use_property_split = False
        col.prop(s, "bake_maps")
        box.prop(s, "texture_size")
        box.prop(s, "bake_samples")
        box.prop(s, "bake_margin")
        box.prop(s, "cage_extrusion")
        box.prop(s, "max_ray_distance")
        box.prop(s, "device")
        box.prop(s, "output_dir")
        box.prop(s, "image_format")

        col = layout.column(heading="Cleanup")
        col.prop(s, "keep_high_poly")
        col.prop(s, "hide_sources")

        layout.separator()
        row = layout.row()
        row.scale_y = 1.5
        row.operator("object.smart_retopo", icon="MOD_REMESH")


def menu_func(self, context):
    self.layout.operator("object.smart_retopo", icon="MOD_REMESH")


classes = (VIEW3D_PT_smart_retopo,)
