"""
tests/test_routes_llm.py

Unit tests for:
  - control_center.api.routes_llm  (GET /llms, GET /knowledge-base)

Covers Ollama status/model parsing for GET /llms, and GET /knowledge-base's
abstract/index directory scanning helpers (_count_json_files,
_list_index_domains, _index_size_bytes -- excluding embedding-checkpoint
scratch files, skipping unreadable/non-directory entries) plus the
route's rag_status derivation from the RAG service's own health response.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import asyncio
import json
import os
import struct as _struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.api import routes_llm
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

# Route exposure: llm_router has NO blanket gate -- GET /llms is
# deliberately public. GET /knowledge-base (2026-09-12 decision) always
# returns its aggregate fields, but only includes pubmed_root/index_root
# when the caller's token carries platform.manage_infra (checked via
# _has_permission, not a hard Depends -- see test_main.py's
# TestKnowledgeBasePublicFields for the access-split checks). These
# tests exercise the routes' own logic, not authorization, so the
# client carries a fixed always-sufficient token by default -- harmless
# for /llms, and means pubmed_root/index_root are populated below
# wherever the underlying dirs exist, same convention as
# test_routes_docker.py.
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
client = TestClient(app, headers={"Authorization": f"Bearer {_INFRA_TOKEN}"})


def _mock_async_client(get_side_effect=None, get_return_value=None):
    """Build a MagicMock standing in for `httpx.AsyncClient(...)` used as an
    `async with` context manager, whose `.get(...)` is an AsyncMock."""
    mock_client = MagicMock()
    mock_get = AsyncMock()
    if get_side_effect is not None:
        mock_get.side_effect = get_side_effect
    else:
        mock_get.return_value = get_return_value
    mock_client.get = mock_get

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


# ==============================================================================
# GET /llms
# ==============================================================================

class TestGetLlms(unittest.TestCase):
    """GET /llms's Ollama status/model parsing and api_keys reporting."""

    def test_ollama_unreachable_on_exception(self) -> None:
        """An Ollama connection failure reports status="unreachable"
        with an empty models list."""
        ctx = _mock_async_client(get_side_effect=RuntimeError("connection refused"))
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            resp = client.get("/llms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["ollama"]["status"], "unreachable")
        self.assertEqual(data["ollama"]["models"], [])

    def test_ollama_non_200_stays_unreachable(self) -> None:
        """A non-200 Ollama response also reports status="unreachable"."""
        mock_resp = MagicMock(status_code=404)
        ctx = _mock_async_client(get_return_value=mock_resp)
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            resp = client.get("/llms")
        data = resp.json()
        self.assertEqual(data["ollama"]["status"], "unreachable")

    def test_ollama_running_parses_models(self) -> None:
        """A successful Ollama response parses each model's size (bytes
        to GB) and modified date, defaulting missing fields to 0.0/""."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3", "size": 4_000_000_000, "modified_at": "2026-07-01T00:00:00Z"},
                {"name": "mistral"},
            ]
        }
        ctx = _mock_async_client(get_return_value=mock_resp)
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            resp = client.get("/llms")
        data = resp.json()
        self.assertEqual(data["ollama"]["status"], "running")
        models = data["ollama"]["models"]
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["name"], "llama3")
        self.assertEqual(models[0]["size_gb"], 4.0)
        self.assertEqual(models[0]["modified"], "2026-07-01")
        self.assertEqual(models[1]["size_gb"], 0.0)
        self.assertEqual(models[1]["modified"], "")

    def test_api_keys_reflect_env(self) -> None:
        """api_keys.configured for each provider reflects whether its
        env var is actually set."""
        ctx = _mock_async_client(get_side_effect=RuntimeError("down"))
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                resp = client.get("/llms")
        data = resp.json()
        self.assertTrue(data["api_keys"]["anthropic"]["configured"])
        self.assertFalse(data["api_keys"]["openai"]["configured"])


# ==============================================================================
# Helper: _count_json_files
# ==============================================================================

class TestCountJsonFiles(unittest.TestCase):
    """_count_json_files()'s per-domain .json count, skipping non-JSON
    files, non-directory entries, and unreadable domain dirs."""

    def test_counts_json_files_across_domains(self) -> None:
        """Total and per-domain counts include only .json files, across
        every domain subdirectory, excluding empty domains from the list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cancer").mkdir()
            (root / "cancer" / "a.json").write_text("{}")
            (root / "cancer" / "b.json").write_text("{}")
            (root / "cancer" / "notes.txt").write_text("x")
            (root / "genomics").mkdir()
            (root / "genomics" / "c.json").write_text("{}")
            (root / "empty_domain").mkdir()

            total, domains = routes_llm._count_json_files(root)

        self.assertEqual(total, 3)
        self.assertEqual(sorted(domains), ["cancer", "genomics"])

    def test_nonexistent_dir_returns_zero(self) -> None:
        """A nonexistent root directory returns (0, [])."""
        total, domains = routes_llm._count_json_files(Path("/nonexistent/abstracts"))
        self.assertEqual(total, 0)
        self.assertEqual(domains, [])

    def test_file_instead_of_dir_entry_skipped(self) -> None:
        """A file directly under the root (not a domain subdirectory)
        is skipped, not counted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not_a_dir.json").write_text("{}")
            total, domains = routes_llm._count_json_files(root)
        self.assertEqual(total, 0)
        self.assertEqual(domains, [])

    def test_unreadable_domain_dir_skipped(self) -> None:
        """A domain directory with no read permission is skipped
        rather than raising a PermissionError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = root / "locked"
            domain.mkdir()
            (domain / "a.json").write_text("{}")
            os.chmod(domain, 0o000)
            try:
                total, domains = routes_llm._count_json_files(root)
            finally:
                os.chmod(domain, 0o755)
        self.assertEqual(total, 0)
        self.assertEqual(domains, [])


# ==============================================================================
# Helper: _list_index_domains
# ==============================================================================

class TestListIndexDomains(unittest.TestCase):
    """_list_index_domains()'s listing of non-empty index domain
    subdirectories, skipping empty ones, files, and unreadable dirs."""

    def test_lists_nonempty_domain_dirs(self) -> None:
        """Only a domain directory with actual content is listed --
        an empty one and a non-directory entry are excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cancer").mkdir()
            (root / "cancer" / "index.faiss").write_text("x")
            (root / "empty").mkdir()
            (root / "not_a_dir.txt").write_text("x")

            domains = routes_llm._list_index_domains(root)

        self.assertEqual(domains, ["cancer"])

    def test_nonexistent_dir_returns_empty(self) -> None:
        """A nonexistent root directory returns an empty list."""
        domains = routes_llm._list_index_domains(Path("/nonexistent/index"))
        self.assertEqual(domains, [])

    def test_unreadable_domain_dir_skipped(self) -> None:
        """A domain directory with no read permission is skipped
        rather than raising."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            domain = root / "locked"
            domain.mkdir()
            (domain / "idx.faiss").write_text("x")
            os.chmod(domain, 0o000)
            try:
                domains = routes_llm._list_index_domains(root)
            finally:
                os.chmod(domain, 0o755)
        self.assertEqual(domains, [])


# ==============================================================================
# Helper: _index_size_bytes
# ==============================================================================

class TestDuBytes(unittest.TestCase):
    """_index_size_bytes()'s recursive byte-size total, excluding
    embedding-checkpoint scratch files, failing safe to 0 on any error."""

    def test_returns_parsed_bytes(self) -> None:
        """The total is the sum of every real index file's byte size,
        recursively across subdirectories."""
        with tempfile.TemporaryDirectory() as tmp:
            domain_dir = Path(tmp) / "CRISPR"
            domain_dir.mkdir()
            (domain_dir / "pubmed_index.faiss").write_bytes(b"x" * 100)
            (domain_dir / "pmid_map.json").write_bytes(b"y" * 23)

            result = routes_llm._index_size_bytes(Path(tmp))
        self.assertEqual(result, 123)

    def test_exception_returns_zero(self) -> None:
        """A nonexistent path returns 0 rather than raising."""
        result = routes_llm._index_size_bytes(Path("/nonexistent/path/does/not/exist"))
        self.assertEqual(result, 0)

    def test_excludes_embedding_checkpoint_scratch_files(self) -> None:
        """A transient embedding_checkpoint_*.json scratch file is
        excluded from the total -- it isn't part of the real index."""
        with tempfile.TemporaryDirectory() as tmp:
            domain_dir = Path(tmp) / "CRISPR"
            domain_dir.mkdir()
            (domain_dir / "pubmed_index.faiss").write_bytes(b"x" * 100)
            (domain_dir / "embedding_checkpoint_1.json").write_bytes(b"z" * 999)

            result = routes_llm._index_size_bytes(Path(tmp))
        self.assertEqual(result, 100)


# ==============================================================================
# GET /knowledge-base
# ==============================================================================

class TestGetKnowledgeBase(unittest.TestCase):
    """GET /knowledge-base's end-to-end abstract/index discovery and
    rag_status derivation from RAG's own health response. Each test uses a
    fresh background scanner and runs its scan synchronously first, the
    way the startup warm-up would."""

    def setUp(self) -> None:
        self.scanner = routes_llm._KnowledgeBaseScanner()
        patcher = patch.object(routes_llm, "scanner", self.scanner)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_data_dirs_found(self) -> None:
        """With no PubMed data directories at all, pubmed_root/index_root
        are None, abstracts.total is 0, and rag_status is "unreachable"."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            ctx = _mock_async_client(get_side_effect=RuntimeError("down"))
            try:
                self.scanner.refresh()
                with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
                    resp = client.get("/knowledge-base")
            finally:
                del os.environ["WORKSPACE_ROOT"]

        data = resp.json()
        self.assertIsNone(data["pubmed_root"])
        self.assertIsNone(data["index_root"])
        self.assertEqual(data["abstracts"]["total"], 0)
        self.assertEqual(data["rag_status"], "unreachable")

    def test_finds_abstracts_and_index(self) -> None:
        """A real PubMed data layout is discovered: abstracts/index
        counts and domain lists reflect the actual files on disk, and
        rag_status is "running" when RAG reports healthy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            abstracts = root / "data" / "PubMed" / "Abstracts" / "cancer"
            abstracts.mkdir(parents=True)
            (abstracts / "a.json").write_text("{}")
            index = root / "data" / "PubMed" / "Index" / "cancer"
            index.mkdir(parents=True)
            (index / "idx.faiss").write_text("x")

            os.environ["WORKSPACE_ROOT"] = tmp

            mock_resp = MagicMock(status_code=200)
            ctx = _mock_async_client(get_return_value=mock_resp)

            try:
                self.scanner.refresh()
                with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
                    resp = client.get("/knowledge-base")
            finally:
                del os.environ["WORKSPACE_ROOT"]

        data = resp.json()
        self.assertEqual(data["rag_status"], "running")
        self.assertEqual(data["abstracts"]["total"], 1)
        self.assertEqual(data["abstracts"]["domains_with_abstracts"], 1)
        self.assertEqual(data["faiss_index"]["domains_indexed"], 1)
        self.assertIn("cancer", data["faiss_index"]["domain_list"])

    def test_rag_degraded_on_non_200(self) -> None:
        """A non-200 response from the RAG service maps to
        rag_status="degraded"."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            mock_resp = MagicMock(status_code=500)
            ctx = _mock_async_client(get_return_value=mock_resp)
            try:
                self.scanner.refresh()
                with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
                    resp = client.get("/knowledge-base")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.json()["rag_status"], "degraded")



# ---------------------------------------------------------------------------
# Re-indexing readiness (public Literature AI progress)
# ---------------------------------------------------------------------------


def _write_faiss(path: Path, dim: int, fourcc: bytes = b"IxFI") -> None:
    path.write_bytes(fourcc + _struct.pack("<i", dim) + _struct.pack("<q", 5) + b"\0" * 16)


class TestIndexReadiness(unittest.TestCase):
    """_index_readiness counts domains the retrieval service can query:
    an index at the configured dimension plus a PMID map."""

    def test_counts_ready_mismatched_missing_map_and_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, dim, with_map in (("ready", 1024, True), ("old", 768, True), ("nomap", 1024, False)):
                (root / name).mkdir()
                _write_faiss(root / name / "pubmed_index.faiss", dim)
                if with_map:
                    (root / name / "pmid_map.json").write_text("[]")
            (root / "other_name").mkdir()
            _write_faiss(root / "other_name" / "custom.faiss", 1024)
            (root / "other_name" / "pmid_map.json").write_text("[]")
            (root / "broken").mkdir()
            (root / "broken" / "pubmed_index.faiss").write_bytes(b"xx")
            (root / "noindex").mkdir()
            (root / "noindex" / "pmid_map.json").write_text("[]")
            result = routes_llm._index_readiness(root, 1024)
        self.assertEqual(result, {
            "expected_dimension": 1024,
            "domains_total": 6,
            "domains_ready": 2,
            "domains_by_dimension": {"1024": 3, "768": 1},
            "missing_map": 1,
            "unreadable": 2,
        })

    def test_faiss_dimension_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zero = Path(tmp) / "zero.faiss"
            _write_faiss(zero, 0)
            self.assertIsNone(routes_llm._faiss_dimension(zero))
            self.assertIsNone(routes_llm._faiss_dimension(Path(tmp) / "missing.faiss"))


class TestKnowledgeBaseScanner(unittest.TestCase):
    """The multi-minute filesystem scan runs off the request path, one at
    a time; requests read the last completed result."""

    def test_pending_before_first_scan_triggers_background_scan(self) -> None:
        fresh = routes_llm._KnowledgeBaseScanner(scan=lambda: {"abstracts": {"total": 1}})
        with patch.object(routes_llm, "scanner", fresh), \
                patch.object(fresh, "refresh_in_background", return_value=True) as start, \
                patch.object(routes_llm.httpx, "AsyncClient", side_effect=Exception("no rag")):
            data = TestClient(app).get("/knowledge-base").json()
        start.assert_called_once()
        self.assertEqual(data["scan"], {"status": "pending", "scanned_at": None})
        self.assertIsNone(data["abstracts"]["total"])
        self.assertEqual(data["faiss_index"]["domain_list"], [])
        self.assertIsNone(data["readiness"])

    def test_serves_last_scan_without_rescanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_root = Path(tmp) / "data" / "PubMed" / "Index"
            (index_root / "cancer").mkdir(parents=True)
            _write_faiss(index_root / "cancer" / "pubmed_index.faiss", 1024)
            (index_root / "cancer" / "pmid_map.json").write_text("[]")
            fresh = routes_llm._KnowledgeBaseScanner()
            env = {"WORKSPACE_ROOT": tmp, "PUBLIC_CACHE_SECONDS": "60"}
            with patch.dict(os.environ, env), patch.object(routes_llm, "scanner", fresh), \
                    patch.object(routes_llm.httpx, "AsyncClient", side_effect=Exception("no rag")):
                fresh.refresh()
                with patch.object(routes_llm, "_scan_knowledge_base") as rescan:
                    anonymous = TestClient(app).get("/knowledge-base")  # public dashboard: no token
                    operator = client.get("/knowledge-base").json()
                rescan.assert_not_called()
        data = anonymous.json()
        self.assertEqual(data["scan"]["status"], "ready")
        self.assertIsNotNone(data["scan"]["scanned_at"])
        self.assertEqual(data["readiness"]["domains_ready"], 1)
        self.assertEqual(data["rag_status"], "unreachable")
        self.assertEqual(anonymous.headers["cache-control"], "public, max-age=60")
        self.assertIsNone(data["index_root"])            # path stays operator-only
        self.assertIsNotNone(operator["index_root"])

    def test_only_one_scan_runs_at_a_time(self) -> None:
        started, release = threading.Event(), threading.Event()
        calls = []

        def slow_scan() -> dict:
            calls.append(1)
            started.set()
            release.wait(5)
            return {"n": len(calls)}

        fresh = routes_llm._KnowledgeBaseScanner(scan=slow_scan)
        self.assertTrue(fresh.refresh_in_background())
        self.assertTrue(started.wait(5))
        self.assertFalse(fresh.refresh_in_background())
        self.assertFalse(fresh.refresh())
        self.assertFalse(fresh.maybe_refresh())
        release.set()
        for _ in range(100):
            if fresh.snapshot()[0] is not None:
                break
            time.sleep(0.01)
        self.assertEqual(fresh.snapshot()[0], {"n": 1})
        self.assertEqual(len(calls), 1)

    def test_staleness_follows_refresh_interval(self) -> None:
        fresh = routes_llm._KnowledgeBaseScanner(scan=lambda: {}, refresh_seconds=100)
        self.assertTrue(fresh.is_stale())
        fresh.refresh()
        self.assertFalse(fresh.is_stale())
        self.assertTrue(fresh.is_stale(now=time.monotonic() + 101))
        with patch.object(fresh, "refresh_in_background", return_value=True) as start:
            self.assertFalse(fresh.maybe_refresh())
            start.assert_not_called()

    def test_default_interval_and_failed_scan_keeps_last_result(self) -> None:
        self.assertEqual(routes_llm._KnowledgeBaseScanner().refresh_seconds,
                         routes_llm.KNOWLEDGE_BASE_REFRESH_SECONDS)
        results = [{"total": 1}, RuntimeError("disk gone")]

        def scan() -> dict:
            value = results.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        fresh = routes_llm._KnowledgeBaseScanner(scan=scan)
        fresh.refresh()
        self.assertTrue(fresh.refresh())      # attempted, logged, not raised
        self.assertEqual(fresh.snapshot()[0], {"total": 1})


if __name__ == "__main__":
    unittest.main()
