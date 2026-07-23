"""
tests/test_routes_llm.py

Unit tests for:
  - control_center.api.routes_llm  (GET /llms, GET /knowledge-base)
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from control_center.api import routes_llm
from control_center.main import app

client = TestClient(app)


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

    def test_ollama_unreachable_on_exception(self) -> None:
        ctx = _mock_async_client(get_side_effect=RuntimeError("connection refused"))
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            resp = client.get("/llms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["ollama"]["status"], "unreachable")
        self.assertEqual(data["ollama"]["models"], [])

    def test_ollama_non_200_stays_unreachable(self) -> None:
        mock_resp = MagicMock(status_code=404)
        ctx = _mock_async_client(get_return_value=mock_resp)
        with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
            resp = client.get("/llms")
        data = resp.json()
        self.assertEqual(data["ollama"]["status"], "unreachable")

    def test_ollama_running_parses_models(self) -> None:
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

    def test_counts_json_files_across_domains(self) -> None:
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
        total, domains = routes_llm._count_json_files(Path("/nonexistent/abstracts"))
        self.assertEqual(total, 0)
        self.assertEqual(domains, [])

    def test_file_instead_of_dir_entry_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not_a_dir.json").write_text("{}")
            total, domains = routes_llm._count_json_files(root)
        self.assertEqual(total, 0)
        self.assertEqual(domains, [])

    def test_unreadable_domain_dir_skipped(self) -> None:
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

    def test_lists_nonempty_domain_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cancer").mkdir()
            (root / "cancer" / "index.faiss").write_text("x")
            (root / "empty").mkdir()
            (root / "not_a_dir.txt").write_text("x")

            domains = routes_llm._list_index_domains(root)

        self.assertEqual(domains, ["cancer"])

    def test_nonexistent_dir_returns_empty(self) -> None:
        domains = routes_llm._list_index_domains(Path("/nonexistent/index"))
        self.assertEqual(domains, [])

    def test_unreadable_domain_dir_skipped(self) -> None:
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
# Helper: _du_bytes
# ==============================================================================

class TestDuBytes(unittest.TestCase):

    def test_returns_parsed_bytes(self) -> None:
        async def fake_create_subprocess_exec(*args, **kwargs):
            proc = AsyncMock()
            proc.communicate.return_value = (b"12345\t/some/path\n", b"")
            return proc

        with patch.object(routes_llm.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            result = asyncio.run(routes_llm._du_bytes(Path("/some/path")))
        self.assertEqual(result, 12345)

    def test_exception_returns_zero(self) -> None:
        with patch.object(routes_llm.asyncio, "create_subprocess_exec", side_effect=RuntimeError("boom")):
            result = asyncio.run(routes_llm._du_bytes(Path("/some/path")))
        self.assertEqual(result, 0)


# ==============================================================================
# GET /knowledge-base
# ==============================================================================

class TestGetKnowledgeBase(unittest.TestCase):

    def test_no_data_dirs_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            ctx = _mock_async_client(get_side_effect=RuntimeError("down"))
            try:
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

            async def fake_create_subprocess_exec(*args, **kwargs):
                proc = AsyncMock()
                proc.communicate.return_value = (b"1024\t/idx\n", b"")
                return proc

            try:
                with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
                    with patch.object(routes_llm.asyncio, "create_subprocess_exec",
                                       side_effect=fake_create_subprocess_exec):
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
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            mock_resp = MagicMock(status_code=500)
            ctx = _mock_async_client(get_return_value=mock_resp)
            try:
                with patch.object(routes_llm.httpx, "AsyncClient", return_value=ctx):
                    resp = client.get("/knowledge-base")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.json()["rag_status"], "degraded")


if __name__ == "__main__":
    unittest.main()
