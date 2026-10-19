# SPDX-FileCopyrightText: 2026 Magnopus LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for scripts/extension_channels.py. Stdlib only:

    python3 -m unittest discover -s tests/ci -p 'test_*.py'
"""

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("extension_channels", ROOT / "scripts" / "extension_channels.py")
ec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ec)


def rel(tag, prerelease=False, draft=False):
    return {"tagName": tag, "isPrerelease": prerelease, "isDraft": draft}


class Pick(unittest.TestCase):
    def test_no_releases(self):
        self.assertEqual(ec.pick([]), {"stable": "", "beta": ""})

    def test_newest_stable_by_semver_not_list_order(self):
        releases = [rel("v0.9.0"), rel("v0.10.0"), rel("v0.2.1")]
        self.assertEqual(ec.pick(releases), {"stable": "v0.10.0", "beta": "v0.10.0"})

    def test_release_candidate_goes_to_beta_only(self):
        releases = [rel("v0.2.0"), rel("v0.3.0-rc.1", prerelease=True)]
        self.assertEqual(ec.pick(releases), {"stable": "v0.2.0", "beta": "v0.3.0-rc.1"})

    def test_final_release_supersedes_its_candidate_in_beta(self):
        releases = [rel("v0.3.0-rc.2", prerelease=True), rel("v0.3.0")]
        self.assertEqual(ec.pick(releases), {"stable": "v0.3.0", "beta": "v0.3.0"})

    def test_candidates_order_numerically(self):
        releases = [rel("v0.3.0-rc.9", True), rel("v0.3.0-rc.10", True), rel("v0.2.0")]
        self.assertEqual(ec.pick(releases)["beta"], "v0.3.0-rc.10")

    def test_pulled_release_falls_back_to_previous(self):
        releases = [rel("v0.2.0"), rel("v0.2.1", prerelease=True)]
        self.assertEqual(ec.pick(releases), {"stable": "v0.2.0", "beta": "v0.2.0"})

    def test_drafts_and_non_semver_tags_are_ignored(self):
        releases = [rel("v0.2.0"), rel("v0.4.0", draft=True), rel("nightly"), rel("v1.0")]
        self.assertEqual(ec.pick(releases), {"stable": "v0.2.0", "beta": "v0.2.0"})

    def test_only_candidates(self):
        releases = [rel("v0.1.0-rc.1", True)]
        self.assertEqual(ec.pick(releases), {"stable": "", "beta": "v0.1.0-rc.1"})


class SemverKey(unittest.TestCase):
    def test_precedence(self):
        tags = ["v1.0.0", "v1.0.0-rc.1", "v1.0.0-alpha", "v1.0.0-alpha.1", "v1.0.0-beta.11", "v1.0.0-beta.2"]
        expected = ["v1.0.0-alpha", "v1.0.0-alpha.1", "v1.0.0-beta.2", "v1.0.0-beta.11", "v1.0.0-rc.1", "v1.0.0"]
        self.assertEqual(sorted(tags, key=ec.semver_key), expected)

    def test_rejects_non_semver(self):
        with self.assertRaises(ValueError):
            ec.semver_key("0.1.0")


if __name__ == "__main__":
    unittest.main()
