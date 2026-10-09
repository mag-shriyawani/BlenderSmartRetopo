#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

# Build the installable extension zip into dist/.
# Uses Blender's extension builder if `blender` is on PATH (or $BLENDER), else plain zip.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-blender}"
VERSION="$(grep -E '^version' "$ROOT/smart_retopo/blender_manifest.toml" | sed -E 's/.*"(.*)".*/\1/')"
mkdir -p "$ROOT/dist"
if command -v "$BLENDER" >/dev/null 2>&1; then
  "$BLENDER" --command extension build --source-dir "$ROOT/smart_retopo" --output-dir "$ROOT/dist"
else
  OUT="$ROOT/dist/smart_retopo-$VERSION.zip"
  rm -f "$OUT"
  (cd "$ROOT" && zip -r "$OUT" smart_retopo -x '*__pycache__*')
  echo "Built $OUT"
fi
