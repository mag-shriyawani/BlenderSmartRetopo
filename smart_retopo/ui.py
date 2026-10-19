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

        has_low = bool(s.low_poly_object)
        n = len([o for o in context.selected_objects
                 if o.type == "MESH" and o.name != s.low_poly_object])
        layout.label(text=f"{n} source mesh object(s) selected", icon="OBJECT_DATA")
        layout.prop(s, "name")

        box = layout.box()
        box.label(text="Retopology", icon="MOD_REMESH")
        box.prop_search(s, "low_poly_object", bpy.data, "objects", icon="MESH_DATA")
        if has_low:
            lp = bpy.data.objects.get(s.low_poly_object)
            if lp is None or lp.type != "MESH":
                box.label(text="Not a mesh object in this file", icon="ERROR")
        qf = box.column()
        qf.active = not has_low  # QuadriFlow settings are ignored with a provided low-poly
        qf.prop(s, "target_faces")
        qf.prop(s, "voxel_mode")
        if s.voxel_mode != "NEVER":
            qf.prop(s, "voxel_resolution")
        col = qf.column(heading="Options")
        col.prop(s, "use_preserve_sharp")
        col.prop(s, "use_preserve_boundary")
        col.prop(s, "use_mesh_symmetry")
        col.prop(s, "smooth_shading")
        qf.prop(s, "seed")

        box = layout.box()
        box.label(text="UVs", icon="UV")
        if has_low:
            box.row().prop(s, "uv_mode", expand=True)
        if not has_low or s.uv_mode == "GENERATE":
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
        if has_low and s.cage_extrusion == 0 and s.max_ray_distance == 0:
            box.label(text="Auto cage assumes the low-poly hugs the surface", icon="INFO")
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
