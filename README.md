# SmartRetopo

Blender extension (4.2+) that turns arbitrary meshes into low-poly, textured game-ready meshes:
**combine → QuadriFlow retopo → new UVs → Cycles bake**. Built to be driven by automation, and ultimately by Nodey & MCP.

Usage, options, Python API and CLI: see [`smart_retopo/README.md`](smart_retopo/README.md).

## Repo layout

| Path | |
|---|---|
| `smart_retopo/` | The extension package (`blender_manifest.toml`, operator, panel, `core.py` pipeline, `cli.py` headless runner) |
| `tests/test_pipeline.py` | End-to-end test: builds a scene, runs the operator, asserts on mesh/UVs/baked maps |
| `scripts/build.sh` | Builds the installable zip into `dist/` |

## Development

```sh
# Run the test (Blender on PATH, or set BLENDER)
blender -b --factory-startup -P tests/test_pipeline.py
#   ...or with the bpy wheel:  pip install bpy && python tests/test_pipeline.py

# Build the extension zip
./scripts/build.sh            # -> dist/smart_retopo-<version>.zip

# Live-develop (macOS): symlink the package into Blender's user extensions repo.
# Run from the repo root; set BV to your Blender version (e.g. 5.2).
BV=5.2
mkdir -p "$HOME/Library/Application Support/Blender/$BV/extensions/user_default"
ln -sfn "$(git rev-parse --show-toplevel)/smart_retopo" \
  "$HOME/Library/Application Support/Blender/$BV/extensions/user_default/smart_retopo"
# Then in Blender: Preferences > Get Extensions > Refresh, and enable "Smart Retopo".
```

Headless run:

```sh
blender -b -P smart_retopo/cli.py -- -i in.glb -o out.glb --faces 4000 --report result.json
```

Tested with Blender 5.2 LTS.
