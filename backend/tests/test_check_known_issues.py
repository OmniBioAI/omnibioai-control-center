"""
tests/test_check_known_issues.py

Unit tests for:
  - control_center.checks.known_issues
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_center.checks import known_issues


class TestBackfillIds(unittest.TestCase):

    def test_adds_id_to_entries_missing_one(self) -> None:
        issues = [{"title": "a"}, {"title": "b"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertTrue(changed)
        self.assertTrue(all("id" in i for i in result))
        self.assertNotEqual(result[0]["id"], result[1]["id"])

    def test_preserves_other_fields_exactly(self) -> None:
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
        issues = [{"id": "existing-id", "title": "a"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertFalse(changed)
        self.assertEqual(result[0]["id"], "existing-id")

    def test_no_change_when_all_have_ids(self) -> None:
        issues = [{"id": "1", "title": "a"}, {"id": "2", "title": "b"}]
        result, changed = known_issues._backfill_ids(issues)
        self.assertFalse(changed)
        self.assertEqual(result, issues)


class TestLoadIssues(unittest.TestCase):

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(known_issues._load_issues(Path("/nonexistent/file.json")), [])

    def test_malformed_json_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text("not json")
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_non_list_json_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps({"not": "a list"}))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_oserror_on_read_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text("[]")
            with patch.object(known_issues.Path, "read_text", side_effect=OSError("denied")):
                with self.assertRaises(known_issues.KnownIssueError) as ctx:
                    known_issues._load_issues(p)
        self.assertEqual(ctx.exception.status_code, 500)


class TestSaveIssues(unittest.TestCase):

    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "issues.json"
            known_issues._save_issues(p, [{"id": "1", "title": "a"}])
            self.assertEqual(json.loads(p.read_text()), [{"id": "1", "title": "a"}])

    def test_oserror_on_write_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues.Path, "write_text", side_effect=OSError("denied")):
                with self.assertRaises(known_issues.KnownIssueError) as ctx:
                    known_issues._save_issues(p, [])
        self.assertEqual(ctx.exception.status_code, 500)


class TestListKnownIssues(unittest.TestCase):

    def test_returns_empty_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            self.assertEqual(known_issues.list_known_issues(p), [])

    def test_backfills_and_persists_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"title": "no id yet"}]))
            result = known_issues.list_known_issues(p)
            self.assertIn("id", result[0])
            on_disk = json.loads(p.read_text())
            self.assertIn("id", on_disk[0])

    def test_does_not_rewrite_file_when_all_have_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            mtime_before = p.stat().st_mtime
            known_issues.list_known_issues(p)
            self.assertEqual(p.stat().st_mtime, mtime_before)


class TestCreateKnownIssue(unittest.TestCase):

    def test_creates_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            issue = known_issues.create_known_issue(p, {"title": "New issue"})
        self.assertEqual(issue["title"], "New issue")
        self.assertEqual(issue["severity"], "medium")
        self.assertEqual(issue["status"], "open")
        self.assertIn("id", issue)
        self.assertIn("opened_at", issue)

    def test_missing_title_raises_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.create_known_issue(p, {"title": ""})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_severity_raises_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.create_known_issue(p, {"title": "x", "severity": "critical"})

    def test_invalid_status_raises_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.create_known_issue(p, {"title": "x", "status": "wontfix"})

    def test_appends_to_existing_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "existing", "title": "old"}]))
            known_issues.create_known_issue(p, {"title": "new"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(len(on_disk), 2)
        self.assertEqual(on_disk[0]["id"], "existing")

    def test_high_severity_fires_discord_alert(self) -> None:
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
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x", "severity": "medium"})
        mock_notify.assert_not_called()

    def test_low_severity_does_not_fire_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x", "severity": "low"})
        mock_notify.assert_not_called()

    def test_default_severity_medium_does_not_fire_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify") as mock_notify:
                known_issues.create_known_issue(p, {"title": "x"})
        mock_notify.assert_not_called()

    def test_long_description_truncated_in_alert(self) -> None:
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
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            with patch.object(known_issues, "_discord_notify", side_effect=RuntimeError("boom")):
                issue = known_issues.create_known_issue(p, {"title": "x", "severity": "high"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(issue["title"], "x")
        self.assertEqual(len(on_disk), 1)

    def test_alert_not_fired_on_update(self) -> None:
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

    def test_no_description_uses_placeholder(self) -> None:
        with patch.object(known_issues, "_discord_notify") as mock_notify:
            known_issues._alert_high_severity({
                "title": "x", "description": "", "area": "", "opened_at": "2026-01-01",
            })
        args, _ = mock_notify.call_args
        self.assertEqual(args[2], "(no description)")

    def test_missing_area_shows_dash(self) -> None:
        with patch.object(known_issues, "_discord_notify") as mock_notify:
            known_issues._alert_high_severity({
                "title": "x", "description": "d", "area": "", "opened_at": "2026-01-01",
            })
        _, kwargs = mock_notify.call_args
        self.assertEqual(kwargs["fields"]["Area"], "—")


class TestUpdateKnownIssue(unittest.TestCase):

    def test_updates_matching_fields_only(self) -> None:
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
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.update_known_issue(p, "does-not-exist", {"status": "resolved"})
        self.assertEqual(ctx.exception.status_code, 404)

    def test_invalid_severity_raises_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.update_known_issue(p, "abc", {"severity": "nope"})

    def test_invalid_status_raises_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError):
                known_issues.update_known_issue(p, "abc", {"status": "nope"})

    def test_persists_update_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x", "status": "open"}]))
            known_issues.update_known_issue(p, "abc", {"status": "resolved"})
            on_disk = json.loads(p.read_text())
        self.assertEqual(on_disk[0]["status"], "resolved")


class TestDeleteKnownIssue(unittest.TestCase):

    def test_deletes_matching_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}, {"id": "def", "title": "y"}]))
            known_issues.delete_known_issue(p, "abc")
            on_disk = json.loads(p.read_text())
        self.assertEqual(len(on_disk), 1)
        self.assertEqual(on_disk[0]["id"], "def")

    def test_unknown_id_raises_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "issues.json"
            p.write_text(json.dumps([{"id": "abc", "title": "x"}]))
            with self.assertRaises(known_issues.KnownIssueError) as ctx:
                known_issues.delete_known_issue(p, "does-not-exist")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
