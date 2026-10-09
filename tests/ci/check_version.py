# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check the extension version in smart_retopo/blender_manifest.toml.

    python3 tests/ci/check_version.py            # manifest version is valid SemVer
    python3 tests/ci/check_version.py v0.2.0     # ...and matches this release tag

Exits non-zero with a message on the first problem found.
"""

import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "smart_retopo" / "blender_manifest.toml"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")


def main(argv: list[str]) -> int:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    errors = []

    if not SEMVER.match(version):
        errors.append(f"manifest version {version!r} is not SemVer (MAJOR.MINOR.PATCH[-pre])")

    if len(argv) > 1:
        tag = argv[1]
        if tag.removeprefix("v") != version:
            errors.append(f"tag {tag!r} does not match manifest version {version!r}")

    if (ROOT / "smart_retopo" / "__init__.py").read_text(encoding="utf-8").find("bl_info") != -1:
        errors.append("smart_retopo/__init__.py defines bl_info; the manifest is the only version source")

    for e in errors:
        print(f"::error file={MANIFEST.relative_to(ROOT)}::{e}")
    if not errors:
        print(f"version {version} OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
