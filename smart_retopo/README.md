# Smart Retopo (Blender 5.0+)

Combines meshes, retopologizes them with QuadriFlow (or uses a low-poly mesh you provide), generates new UVs (or keeps yours) and bakes the original surface onto the low-poly with Cycles.

## Install

Download `smart_retopo-<version>.zip` from the repo's [Releases](https://github.com/magnopus/BlenderSmartRetopo/releases) page, then Edit > Preferences > Get Extensions > ⌄ > **Install from Disk…** and pick the zip.

## Use (UI)

Select one or more objects → **View3D sidebar (N) > Smart Retopo** → set options → **Smart Retopo**.
Also available in **Object** menu.

To use your own low-poly instead of QuadriFlow, pick it in **Retopology > Low-Poly Mesh**, then choose **UVs: Generate** (unwrap it again) or **Use Existing** (bake into its UV map). Selecting the low-poly too is fine: it's never treated as a source.

## Pipeline

1. **Combine**: evaluates each selected object (modifiers applied, curves/text converted), bakes world transforms and joins them into `<name>_high`. The originals stay untouched.
2. **Retopo**: with a provided low-poly, takes an evaluated, world-space copy of it as `<name>_retopo` (your object isn't modified) and skips the rest of this step. Otherwise it cleans up the mesh (merge by distance, removes loose verts, recalculates normals), then runs QuadriFlow to `target_faces`. With *Voxel Pre-pass = Auto*, a voxel remesh runs first when several objects are combined or the mesh is non-manifold, and also as a fallback if QuadriFlow fails. That gives QuadriFlow a watertight shell.
3. **UVs**: Smart UV Project (or Lightmap Pack), then rotates and packs the islands. With *UVs = Use Existing*, the provided low-poly's render UV map is used as is; the run fails if it has no UV map, and warns if UVs fall outside 0–1.
4. **Bake**: Cycles selected-to-active from high to low. Base Color, Roughness and Metallic are taken straight from each Principled BSDF input through a temporary emission swap, so lighting doesn't affect them and metals don't bake black. Normal (tangent), AO and Emission use the native bake types. The baked maps are wired into a new Principled material. The cage extrusion and ray distance are set automatically from the bounding box when left at 0. That assumes the low-poly hugs the surface; set them yourself if a provided low-poly sits further away.

## Automation

```python
import bpy, json
bpy.ops.object.smart_retopo(target_faces=3000, texture_size=1024,
                            bake_maps={'BASE_COLOR', 'NORMAL', 'ROUGHNESS'},
                            output_dir="/tmp/textures")
result = json.loads(bpy.context.window_manager["smart_retopo_last_result"])

# Your own low-poly, keeping its UVs
bpy.ops.object.smart_retopo(low_poly_object="Chair_LOD2", uv_mode="EXISTING")
```

Calling the operator from Python skips the panel settings and uses the arguments you pass (or the defaults). It blocks until it's done, so you can read the result straight after the call. When you click the button, it uses the panel settings and runs in the background: the panel and status bar show progress, and **Esc** cancels and removes what was made so far.

## Headless / CLI

```
blender -b -P smart_retopo/cli.py -- -i in.glb -o out.glb --faces 4000 --size 2048 \
    --maps BASE_COLOR NORMAL ROUGHNESS METALLIC --report result.json

# Your own low-poly from a separate file (its meshes are joined), keeping its UVs
blender -b -P smart_retopo/cli.py -- -i in.glb -o out.glb --low-poly-file lod2.glb --uv-mode EXISTING
```

`--low-poly NAME` instead picks an object inside the input file.

This runs without installing the add-on. Supported inputs are blend, glb/gltf, fbx, obj, ply, stl and usd. Supported outputs are glb/gltf, fbx, obj, usd and blend. It prints `SMART_RETOPO_RESULT: {json}` and exits with code 1 on failure. `--settings-json` takes any `RetopoSettings` field as a JSON string or file.

## Result JSON

`object_name, material_name, source_objects, source_faces, result_faces, used_voxel_remesh, low_poly_object, uvs_generated, images{map: path|"<packed>"}, timings{combine,retopo,uv,bake,total}, warnings`. The full contract is `docs/result.schema.json` in the repo.

## Notes

- From the UI, Blender stays responsive during the bakes, which run as Blender's bake job with its progress bar in the status bar. QuadriFlow is a single blocking step, so at high face counts Blender can stop responding until it finishes.
- QuadriFlow face counts are approximate.
- Only Principled BSDF inputs are read for socket maps. Other shaders fall back to defaults.
- AO is baked but not wired into the material, because Principled has no AO input.

## License

Copyright 2026 Magnopus LLC. Licensed under the GNU General Public License v3.0 or later; see `LICENSE` in this package.
