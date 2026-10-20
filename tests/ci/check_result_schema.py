# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keep docs/result.schema.json in sync with the code. Stdlib only, no Blender.

    python3 tests/ci/check_result_schema.py                 # schema vs RetopoResult / ALL_MAPS
    python3 tests/ci/check_result_schema.py result.json     # ...and validate a real result file

The schema is the contract Nodey and the MCP tool rely on. This check fails if a
RetopoResult field is added, renamed or removed without updating the schema
(and so without a deliberate, reviewed interface change).
"""

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "result.schema.json"
SETTINGS = ROOT / "smart_retopo" / "core" / "settings.py"
CLI_ONLY = {"ok", "output", "error"}
TIMING_KEYS = {"combine", "retopo", "uv", "bake", "total"}


def load_settings():
    # settings.py has no bpy import; load it directly so the bpy-importing
    # package __init__ files are not executed.
    spec = importlib.util.spec_from_file_location("smart_retopo_settings", SETTINGS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate(result: dict, schema: dict) -> list[str]:
    """Minimal validator for the shapes this schema uses."""
    errors = []
    props = schema["properties"]
    if result.get("ok") is False:
        required = ["ok", "error"]
    else:
        required = schema["required"]
    for key in required:
        if key not in result:
            errors.append(f"missing key {key!r}")
    for key, value in result.items():
        if key not in props:
            errors.append(f"unexpected key {key!r}")
            continue
        spec = props[key]
        expected = TYPES[spec["type"]]
        if isinstance(value, bool) and spec["type"] in ("integer", "number"):
            errors.append(f"{key}: expected {spec['type']}, got bool")
        elif not isinstance(value, expected):
            errors.append(f"{key}: expected {spec['type']}, got {type(value).__name__}")
        elif "enum" in spec and value not in spec["enum"]:
            errors.append(f"{key}: {value!r} is not one of {spec['enum']}")
        elif spec["type"] == "object":
            allowed = set(spec.get("propertyNames", {}).get("enum", []))
            for k in value:
                if allowed and k not in allowed:
                    errors.append(f"{key}: unexpected key {k!r}")
    return errors


def main(argv: list[str]) -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    settings = load_settings()
    fields = set(settings.RetopoResult.__dataclass_fields__)
    props = set(schema["properties"])
    errors = []

    if props - CLI_ONLY != fields:
        errors.append(
            f"schema properties {sorted(props - CLI_ONLY)} != RetopoResult fields {sorted(fields)}"
        )
    if set(schema["required"]) != fields:
        errors.append("schema 'required' must list exactly the RetopoResult fields")
    maps = set(schema["properties"]["images"]["propertyNames"]["enum"])
    if maps != set(settings.ALL_MAPS):
        errors.append(f"images keys {sorted(maps)} != ALL_MAPS {sorted(settings.ALL_MAPS)}")
    devices = set(schema["properties"]["bake_device"]["enum"])
    if devices != {"", "CPU", *settings.GPU_BACKENDS}:
        errors.append(f"bake_device values {sorted(devices)} != '', CPU and GPU_BACKENDS")
    timings = set(schema["properties"]["timings"]["propertyNames"]["enum"])
    if timings != TIMING_KEYS:
        errors.append(f"timings keys {sorted(timings)} != {sorted(TIMING_KEYS)}")

    for path in argv[1:]:
        result = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        errors += [f"{path}: {e}" for e in validate(result, schema)]

    for e in errors:
        print(f"::error file=docs/result.schema.json::{e}")
    if not errors:
        print("result schema OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
