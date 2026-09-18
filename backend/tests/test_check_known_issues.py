"""
tests/test_check_known_issues.py

Unit tests for:
  - control_center.checks.known_issues

Covers id backfilling for legacy entries, file load/save error mapping
to typed KnownIssueError status codes, and the full CRUD surface
(list/create/update/delete) including validation, the high-severity
Discord alert (fired only on create, never on update, with description
truncation and best-effort failure isolation), and persistence to disk.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_center.checks import known_issues


class TestBackfillIds(unittest.TestCase):
    """_backfill_ids()'s id-generation for legacy entries missing one,
    leaving already-id'd entries untouched."""

    def test_adds_id_to_entries_missing_one(self) -> None:
        """Every entry missing an "id" gets a distinct one generated,
        and changed=True is reported."""
        issues = [{"title": "a"}, {"title": "b"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertTrue(changed)
        self.assertTrue(all("id" in i for i in result))
        self.assertNotEqual(result[0]["id"], result[1]["id"])

    def test_preserves_other_fields_exactly(self) -> None:
        """Backfilling an id leaves every other field of the entry unchanged."""
        issue = {
            "title": "GPU issue", "description": "desc", "severity": "medium",
            "opened_at": "2026-07-24", "status": "acknowledged", "area": "GPU / Infra",
        }
        result, changed = known_issues._backfill_ids([dict(issue)])
        self.assertTrue(changed)
        backfilled = result[0]
        for key, value in issue.items():
            self.assertEqual(backfilled[key], value)
        self.assertIn("id", backfilled)

    def test_leaves_existing_id_untouched(self) -> None:
        """An entry that already has an id keeps its exact value, and
        changed=False is reported."""
        issues = [{"id": "existing-id", "title": "a"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertFalse(changed)
        self.assertEqual(result[0]["id"], "existing-id")

    def test_no_change_when_all_have_ids(self) -> None:
        """When every entry already has an id, changed=False and the
        list is returned unmodified."""
        issues = [{"id": "1", "title": "a"}, {"id": "2", "title": "b"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertFalse(changed)
        self.assertEqual(result, issues)


class TestLoadIssues(unittest.TestCase):
    """_load_issues()'s file-load error mapping to KnownIssueError(500)."""

    def test_missing_file_returns_empty_list(self) -> None:
        """A nonexistent file returns an empty list, not an error."""
        self.assertEqual(known_issues._load_issues(Path("/nonexistent/file.json")), [])

    def test_malformed_json_raises_500(self) -> None:
        """Non-JSON file content raises KnownIssueError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text("not json")
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_non_list_json_raises_500(self) -> None:
        """Valid JSON that isn't a list (e.g. a dict) raises KnownIssueError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps({"not": "a list"}))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_oserror_on_read_raises_500(self) -> None:
        """An OSError while reading the file raises KnownIssueError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text("[]")
            with patch.object(known_issues.Path, "read_text", side_effect=OSError("denied")):
                with self.assertRaises(known_issues.KnownIssueError) as ctx:
                    known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)


class TestSaveIssues(unittest.TestCase):
    """_save_issues()'s file-write behavior and error mapping to KnownIssueError(500)."""

    def test_writes_valid_json(self) -> None:
        """A write creates any missing parent directory and produces
        exactly the given issues list as valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "issues.json"
            known_issues._save_issues(p, [{"id": "1", "title": "a"}])
            self.assertEqual(json.loads(p.read_text()), [{"id": "1", "title": "a"}])

    def test_oserror_on_write_raises_500(self) -> None:
        """An OSError while writing the file raises KnownIssueError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues.Path, "write_text", side_effect=OSError("denied")):
                with self.assertRaises(known_issues.KnownIssueError) as ctx:
                    known_issues._save_issues(p, [])
        self.assertEqual(ctx.exception.status_code, 500)


class TestListKnownIssues(unittest.TestCase):
    """list_known_issues()'s id-backfill-and-persist-once-if-needed behavior."""

    def test_returns_empty_for_missing_file(self) -> None:
        """A nonexistent file returns an empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            self.assertEqual(known_issues.list_known_issues(p), [])

    def test_backfills_and_persists_ids(self) -> None:
        """An entry missing an id gets one backfilled in the returned
        result AND written back to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"title": "no id yet"}]))
            result = known_issues.list_known_issues(p)
            self.assertIn("id", result[0])
            on_disk = json.loads(p.read_text())
            self.assertIn("id", on_disk[0])

    def test_does_not_rewrite_file_when_all_have_ids(self) -> None:
        """When no backfill is needed, the file's mtime is untouched --
        no unnecessary rewrite."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            mtime_before = p.stat().st_mtime
            known_issues.list_known_issues(p)
            self.assertEqual(p.stat().st_mtime, mtime_before)


class TestCreateKnownIssue(unittest.TestCase):
    """create_known_issue()'s defaults, validation, persistence, and
    high-severity Discord alerting."""

    def test_creates_with_defaults(self) -> None:
        """A minimal payload gets sensible defaults: severity=medium,
        status=open, a generated id, and an opened_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            issue = known_issues.create_known_issue(p, {"title": "New issue"})
        self.assertEqual(issue["title"], "New issue")
        self.assertEqual(issue["severity"], "medium")
        self.assertEqual(issue["status"], "open")
        self.assertIn("id", issue)
        self.assertIn("opened_at", issue)

    def test_missing_title_raises_400(self) -> None:
        """An empty title raises KnownIssueError(400)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.create_known_issue(p, {"title": ""})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_severity_raises_400(self) -> None:
        """An unrecognized severity value raises KnownIssueError."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.create_known_issue(p, {"title": "x", "severity": "critical"})

    def test_invalid_status_raises_400(self) -> None:
        """An unrecognized status value raises KnownIssueError."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.create_known_issue(p, {"title": "x", "status": "wontfix"})

    def test_appends_to_existing_issues(self) -> None:
        """A new issue is appended after existing ones, leaving them unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "existing", "title": "old"}]))
            known_issues.create_known_issue(p, {"title": "new"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(len(on_disk), 2)
        self.assertEqual(on_disk[0]["id"], "existing")

    def test_high_severity_fires_discord_alert(self) -> None:
        """A high-severity issue fires exactly one Discord alert
        naming the title, with an "error" color and the issue's area field."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {
                    "title": "Disk almost full", "severity": "high", "area": "Infra",
                })
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertIn("Disk almost full", args[1])
        self.assertEqual(kwargs["color"], "error")
        self.assertEqual(kwargs["fields"]["Area"], "Infra")

    def test_medium_severity_does_not_fire_alert(self) -> None:
        """A medium-severity issue never fires a Discord alert."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x", "severity": "medium"})
        mock_notify.assert_not_called()

    def test_low_severity_does_not_fire_alert(self) -> None:
        """A low-severity issue never fires a Discord alert."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x", "severity": "low"})
        mock_notify.assert_not_called()

    def test_default_severity_medium_does_not_fire_alert(self) -> None:
        """Omitting severity entirely defaults to medium, which does
        not fire a Discord alert."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x"})
        mock_notify.assert_not_called()

    def test_long_description_truncated_in_alert(self) -> None:
        """A very long description is truncated to the configured
        alert limit with a trailing ellipsis in the Discord alert."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            long_desc = "x" * 1000
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {
                    "title": "x", "severity": "high", "description": long_desc,
                })
        args, _ = mock_notify.call_args
        sent_description = args[2]
        self.assertLessEqual(len(sent_description), known_issues._DESCRIPTION_ALERT_LIMIT + 1)
        self.assertTrue(sent_description.endswith("…"))

    def test_discord_alert_failure_does_not_block_creation(self) -> None:
        """A Discord alert failure never blocks issue creation -- the
        issue is still returned and persisted to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify", side_effect=RuntimeError("boom")):
                issue = known_issues.create_known_issue(p, {"title": "x", "severity": "high"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(issue["title"], "x")
        self.assertEqual(len(on_disk), 1)

    def test_alert_not_fired_on_update(self) -> None:
        """Updating an issue to high severity never fires a Discord
        alert -- alerting only happens on create."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{
                "id": "abc", "title": "x", "description": "", "severity": "low",
                "status": "open", "area": "", "opened_at": "2026-01-01",
            }]))
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.update_known_issue(p, "abc", {"severity": "high"})
        mock_notify.assert_not_called()


class TestAlertHighSeverity(unittest.TestCase):
    """_alert_high_severity()'s formatting of empty optional fields."""

    def test_no_description_uses_placeholder(self) -> None:
        """An empty description is rendered as "(no description)" in the alert."""
        with patch.object(known_issues, "_discord_notify") as mock_notify:
            known_issues._alert_high_severity({
                "title": "x", "description": "", "area": "", "opened_at": "2026-01-01",
            })
        args, _ = mock_notify.call_args
        self.assertEqual(args[2], "(no description)")

    def test_missing_area_shows_dash(self) -> None:
        """An empty area is rendered as an em-dash in the alert's fields."""
        with patch.object(known_issues, "_discord_notify") as mock_notify:
            known_issues._alert_high_severity({
                "title": "x", "description": "d", "area": "", "opened_at": "2026-01-01",
            })
        _, kwargs = mock_notify.call_args
        self.assertEqual(kwargs["fields"]["Area"], "—")


class TestUpdateKnownIssue(unittest.TestCase):
    """update_known_issue()'s partial-update semantics, validation, and
    404-for-unknown-id handling."""

    def test_updates_matching_fields_only(self) -> None:
        """Updating only status leaves every other field (title) unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{
                "id": "abc", "title": "old title", "description": "d",
                "severity": "low", "status": "open", "area": "x", "opened_at": "2026-01-01",
            }]))
            updated = known_issues.update_known_issue(p, "abc", {"status": "resolved"})
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["title"], "old title")

    def test_unknown_id_raises_404(self) -> None:
        """Updating a nonexistent id raises KnownIssueError(404)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.update_known_issue(p, "does-not-exist", {"status": "resolved"})
        self.assertEqual(ctx.exception.status_code, 404)

    def test_invalid_severity_raises_400(self) -> None:
        """An unrecognized severity value raises KnownIssueError."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.update_known_issue(p, "abc", {"severity": "nope"})

    def test_invalid_status_raises_400(self) -> None:
        """An unrecognized status value raises KnownIssueError."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.update_known_issue(p, "abc", {"status": "nope"})

    def test_persists_update_to_disk(self) -> None:
        """An update is written back to the file on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x", "status": "open"}]))
            known_issues.update_known_issue(p, "abc", {"status": "resolved"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(on_disk[0]["status"], "resolved")


class TestDeleteKnownIssue(unittest.TestCase):
    """delete_known_issue()'s removal and 404-for-unknown-id handling."""

    def test_deletes_matching_issue(self) -> None:
        """Deleting a matching id removes only that entry, leaving the
        rest untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}, {"id": "def", "title": "y"}]))
            known_issues.delete_known_issue(p, "abc")
            on_disk = json.loads(p.read_text())
        self.assertEqual(len(on_disk), 1)
        self.assertEqual(on_disk[0]["id"], "def")

    def test_unknown_id_raises_404(self) -> None:
        """Deleting a nonexistent id raises KnownIssueError(404)."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.delete_known_issue(p, "does-not-exist")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
