"""
tests/test_check_integrity.py

Unit tests for:
  - control_center.checks.integrity

Covers run_integrity_checks()'s handling of every configured-entry shape
(missing/malformed system config, an entry with no path, multiple
entries) and every target-path outcome (nonexistent, broken symlink,
empty vs. non-empty directory or file, valid symlink, an OSError during
the size check, and the name-defaults-to-path fallback).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from control_center.checks import integrity
from control_center.checks.integrity import run_integrity_checks


@dataclass
class _FakeSettings:
    system: Any


class TestRunIntegrityChecks(unittest.TestCase):
    """run_integrity_checks()'s handling of every configured-entry shape
    and every target-path status it can classify."""

    def test_no_system_config_returns_empty(self) -> None:
        """settings.system=None returns an empty list."""
        self.assertEqual(run_integrity_checks(_FakeSettings(system=None)), [])

    def test_non_dict_system_returns_empty(self) -> None:
        """A non-dict settings.system returns an empty list."""
        self.assertEqual(run_integrity_checks(_FakeSettings(system="not-a-dict")), [])

    def test_no_integrity_checks_key_returns_empty(self) -> None:
        """A system dict with no "integrity_checks" key returns an empty list."""
        self.assertEqual(run_integrity_checks(_FakeSettings(system={})), [])

    def test_entry_without_path_skipped(self) -> None:
        """An entry missing its "path" key is skipped entirely."""
        settings = _FakeSettings(system={"integrity_checks": [{"name": "no-path"}]})
        self.assertEqual(run_integrity_checks(settings), [])

    def test_nonexistent_path_is_missing(self, ) -> None:
        """A path that doesn't exist is reported status="missing"."""
        settings = _FakeSettings(system={
            "integrity_checks": [{"name": "gone", "path": "/nonexistent/path/xyz"}],
        })
        result = run_integrity_checks(settings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "missing")
        self.assertFalse(result[0]["is_symlink"])
        self.assertFalse(result[0]["target_exists"])

    def test_nonexistent_symlink_target_is_broken(self) -> None:
        """A symlink pointing at a nonexistent target is reported
        status="broken", with resolves_to showing the dangling target."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            link_path = os.path.join(tmp, "broken_link")
            os.symlink("/nonexistent/target/xyz", link_path)
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "broken", "path": link_path}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "broken")
        self.assertTrue(result[0]["is_symlink"])
        self.assertEqual(result[0]["resolves_to"], "/nonexistent/target/xyz")

    def test_empty_directory_is_empty_status(self) -> None:
        """An existing but empty directory is reported status="empty"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = os.path.join(tmp, "empty")
            os.mkdir(empty_dir)
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "empty-dir", "path": empty_dir}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "empty")
        self.assertTrue(result[0]["target_exists"])
        self.assertFalse(result[0]["target_nonempty"])

    def test_nonempty_directory_is_ok(self) -> None:
        """A directory containing a file is reported status="ok"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.mkdir(data_dir)
            with open(os.path.join(data_dir, "file.txt"), "w") as f:
                f.write("x")
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "data", "path": data_dir}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "ok")
        self.assertTrue(result[0]["target_nonempty"])
        self.assertTrue(result[0]["target_readable"])

    def test_empty_file_is_empty_status(self) -> None:
        """A zero-byte file is reported status="empty"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "empty.txt")
            open(file_path, "w").close()
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "empty-file", "path": file_path}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "empty")

    def test_nonempty_file_is_ok(self) -> None:
        """A file with content is reported status="ok"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "data.txt")
            with open(file_path, "w") as f:
                f.write("hello")
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "data-file", "path": file_path}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "ok")

    def test_name_defaults_to_path_when_missing(self) -> None:
        """An entry with no "name" key reports the path itself as the name."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            settings = _FakeSettings(system={"integrity_checks": [{"path": tmp}]})
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["name"], tmp)

    def test_symlink_to_valid_target_is_ok(self) -> None:
        """A symlink to a real, non-empty directory is reported
        status="ok" with resolves_to the real (canonical) target path."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = os.path.join(tmp, "target")
            os.mkdir(target_dir)
            with open(os.path.join(target_dir, "f.txt"), "w") as f:
                f.write("data")
            link_path = os.path.join(tmp, "link")
            os.symlink(target_dir, link_path)
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "linked", "path": link_path}],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "ok")
        self.assertTrue(result[0]["is_symlink"])
        self.assertEqual(result[0]["resolves_to"], os.path.realpath(target_dir))

    def test_oserror_during_size_check_treated_as_empty(self) -> None:
        """An OSError raised while checking the file's size is treated
        as status="empty" rather than raising or reporting "ok"."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "data.txt")
            with open(file_path, "w") as f:
                f.write("hello")
            settings = _FakeSettings(system={
                "integrity_checks": [{"name": "data-file", "path": file_path}],
            })
            with patch.object(integrity.os.path, "getsize", side_effect=OSError("stat failed")):
                result = run_integrity_checks(settings)
        self.assertEqual(result[0]["status"], "empty")
        self.assertFalse(result[0]["target_nonempty"])

    def test_multiple_entries_processed(self) -> None:
        """Multiple configured entries are all processed independently,
        each producing its own result."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            settings = _FakeSettings(system={
                "integrity_checks": [
                    {"name": "a", "path": tmp},
                    {"name": "b", "path": "/nonexistent"},
                ],
            })
            result = run_integrity_checks(settings)
        self.assertEqual(len(result), 2)
        self.assertEqual({r["name"] for r in result}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
