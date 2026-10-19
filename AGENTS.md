# AGENTS.md

Guidance for AI coding agents and new contributors. `CLAUDE.md` is a symlink to this file, so keep it as the single copy.

## What this is

**Smart Retopo** is a Blender **5.0+** extension. It turns arbitrary meshes into a low-poly, UV-mapped, textured mesh: **combine → QuadriFlow retopology → new UVs → Cycles bake** (base color, normal, roughness, metallic, AO, emission).
It's intended for artists: it has an interactive UI and can also be driven by automation.

- Repo: `magnopus/BlenderSmartRetopo`. Distribution: GitHub Releases.
- License: GPL-3.0-or-later, © Magnopus LLC.

## Map

| Path | What |
|---|---|
| `smart_retopo/core/` | The pipeline, UI-free: `settings.py` (`RetopoSettings`, `RetopoResult`, no bpy), `combine.py`, `retopo.py`, `uv.py`, `bake.py`, `pipeline.py` (`smart_retopo()`), `utils.py` |
| `smart_retopo/operators.py`, `props.py`, `ui.py` | The `object.smart_retopo` operator, its shared property mixin, and the sidebar panel |
| `smart_retopo/cli.py` | Headless runner: `blender -b -P smart_retopo/cli.py -- -i in.glb -o out.glb ...` |
| `smart_retopo/blender_manifest.toml` | **Only** source of the version and metadata. No `bl_info`. |
| `tests/test_pipeline.py` | End-to-end test. Writes `tests/_output/result.json`. |
| `tests/ci/` | Stdlib-only checks: `check_version.py`, `check_result_schema.py` |
| `docs/architecture.md` | How the pipeline works, and behaviour that's easy to break. **Read before changing `core/`.** |
| `docs/result.schema.json` | Contract for the result JSON |
| `.github/` | CI (`ci.yml`), releases (`release.yml`), the `setup-blender` action, Dependabot |

## Commands

```sh
# Checks, no Blender needed (CI runs the first three)
ruff check .                                   # lint
reuse lint                                     # every file has copyright + license info
python3 tests/ci/check_version.py              # manifest version is valid SemVer
python3 tests/ci/check_result_schema.py        # docs/result.schema.json matches RetopoResult

# End-to-end test (Blender on PATH, or the bpy wheel: pip install bpy && python3 tests/test_pipeline.py)
blender -b --factory-startup --python-exit-code 1 -P tests/test_pipeline.py
python3 tests/ci/check_result_schema.py tests/_output/result.json   # validate the result the test produced

./scripts/build.sh                             # dist/smart_retopo-<version>.zip
```

Before handing work back, run the checks, and the end-to-end test if you touched anything under `smart_retopo/`.

## Rules

- **Blender 5.0+ only.** Use Blender 5 APIs. Don't add fallbacks for older versions.
- **Never edit the version** in `blender_manifest.toml`, or `CHANGELOG.md`, by hand. release-please owns them.
- **PR titles are Conventional Commits** (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`...); CI enforces this. Commit titles drive the version bumps.
- **Every new source file starts with the two-line SPDX header**, with no blank `#` line between them:
  ```python
  # SPDX-FileCopyrightText: 2026 Magnopus LLC
  # SPDX-License-Identifier: GPL-3.0-or-later
  ```
  Markdown and JSON are covered by `REUSE.toml` instead. `reuse annotate` adds a blank `#` line by default, so remove it.
- **Pipeline logic goes into `core/`**, and must work headless: use `bpy.context.temp_override(...)` or `utils._make_active`, object mode, and no window or UI context.
- **A new setting** needs adding in `RetopoSettings` *and* the `SmartRetopoProps` mixin (`props.py`), plus a flag in `cli.py` if automation needs it.
- **GitHub Actions are pinned to full commit SHAs**, with a `# vX.Y.Z` comment. Keep `permissions:` least-privilege for each job.

## Public interface: changing it is a breaking change

1. **Operator** `bpy.ops.object.smart_retopo(**settings)`. Its properties mirror `RetopoSettings` fields. It writes the result JSON to `bpy.context.window_manager["smart_retopo_last_result"]`. Called from Python, it uses the arguments or the defaults; only the UI button reads the panel values.
2. **CLI** `cli.py` flags, the stdout line `SMART_RETOPO_RESULT: {json}`, `--report <file>`, and exit code 1 on failure (`{"ok": false, "error": ...}`).
3. **Result JSON**, defined by [`docs/result.schema.json`](docs/result.schema.json). `tests/ci/check_result_schema.py` fails if `RetopoResult` and the schema diverge, so update both together.
4. The **minimum Blender version**.

Removing or renaming any of these needs a `!` in the PR title (`feat!:`), or a `BREAKING CHANGE:` footer. Adding optional ones is a `feat:`.

## Gotchas

These are covered in more detail in [`docs/architecture.md`](docs/architecture.md):

- Base color, roughness and metallic are baked by **temporarily swapping material outputs to emission**. Always restore them, even on failure.
- **Source objects are hidden during the bake**, because they'd occlude AO. Don't remove that.
- QuadriFlow needs a manifold mesh. The voxel pre-pass and fallback in `retopo.py` handle that. Its face counts are approximate.
- The **cage extrusion and ray distance** default to 1% and 5% of the bounding-box diagonal when set to 0.
- On failure, the pipeline removes its own `_high` and `_retopo` objects. Keep the scene clean.
- AO is baked but not wired into the material, because Principled has no AO input.

## Releasing

Merging to `main` updates the release-please PR, and merging that PR publishes a tested, checksummed and attested zip. See the [README](README.md#releasing). Don't create tags or releases by hand.
