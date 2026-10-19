# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pick which GitHub release goes into each Blender extension channel.

    gh release list --json tagName,isDraft,isPrerelease --limit 200 \\
      | python3 scripts/extension_channels.py
    stable=v0.2.0
    beta=v0.3.0-rc.1

Prints `name=tag` lines (append them to $GITHUB_OUTPUT); a channel with no
release prints an empty tag. Stdlib only, no Blender.

Rules (a Blender listing holds one version per extension, so one tag each):

- stable: the newest published release that is not marked pre-release and
  whose tag has no SemVer pre-release part (vX.Y.Z).
- beta:   the newest of the stable candidates and the release candidates
  (vX.Y.Z-rc.N and other pre-release tags), so testers always get the
  newest build, release candidate or not.
- pulled: a vX.Y.Z release that has been marked pre-release on GitHub. It is
  left out of both channels, so the channel falls back to the previous
  release. Delete (or re-draft) a release candidate to pull it from beta.

Drafts and tags that are not SemVer are ignored.
"""

from __future__ import annotations

import json
import re
import sys

TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")


def semver_key(tag: str):
    """Sort key implementing SemVer precedence (a pre-release sorts before its release)."""
    m = TAG.match(tag)
    if not m:
        raise ValueError(f"not a SemVer tag: {tag!r}")
    major, minor, patch, pre = m.groups()
    core = (int(major), int(minor), int(patch))
    if pre is None:
        return core + ((1,),)
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return core + ((0, ids),)


def classify(release: dict) -> str | None:
    """Return "stable", "candidate", "pulled", or None to ignore."""
    tag = release.get("tagName", "")
    if release.get("isDraft") or not TAG.match(tag):
        return None
    has_pre = TAG.match(tag).group(4) is not None
    if has_pre:
        return "candidate"
    return "pulled" if release.get("isPrerelease") else "stable"


def pick(releases: list[dict]) -> dict[str, str]:
    stable = [r["tagName"] for r in releases if classify(r) == "stable"]
    candidates = [r["tagName"] for r in releases if classify(r) == "candidate"]
    newest = lambda tags: max(tags, key=semver_key) if tags else ""  # noqa: E731
    return {"stable": newest(stable), "beta": newest(stable + candidates)}


def main() -> int:
    releases = json.load(sys.stdin)
    for name, tag in pick(releases).items():
        print(f"{name}={tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
