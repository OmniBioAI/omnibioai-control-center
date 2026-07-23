"""
tests/test_routes_reference.py

Unit tests for:
  - control_center.api.routes_reference  (GET /reference)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_center.api.routes_reference import _dir_exists_nonempty
from control_center.main import app

client = TestClient(app)


class TestDirExistsNonempty(unittest.TestCase):

    def test_missing_path_is_false(self) -> None:
        self.assertFalse(_dir_exists_nonempty(Path("/nonexistent/path/xyz")))

    def test_file_with_content_is_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "data.txt"
            f.write_text("hello")
            self.assertTrue(_dir_exists_nonempty(f))

    def test_empty_file_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "empty.txt"
            f.write_text("")
            self.assertFalse(_dir_exists_nonempty(f))

    def test_dir_with_nonempty_file_is_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "sub"
            d.mkdir()
            (d / "x.txt").write_text("content")
            self.assertTrue(_dir_exists_nonempty(Path(tmp)))

    def test_dir_with_only_empty_files_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty.txt").write_text("")
            self.assertFalse(_dir_exists_nonempty(Path(tmp)))

    def test_empty_dir_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_dir_exists_nonempty(Path(tmp)))

    def test_rglob_exception_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "rglob", side_effect=OSError("boom")):
                self.assertFalse(_dir_exists_nonempty(Path(tmp)))


class TestGetReference(unittest.TestCase):

    def test_no_ref_root_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        data = resp.json()
        self.assertFalse(data["available"])
        self.assertEqual(data["organisms"], [])
        self.assertEqual(data["databases"], {})
        self.assertEqual(data["annotation"], {})

    def test_ref_root_via_data_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            ref_root.mkdir(parents=True)
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        data = resp.json()
        self.assertTrue(data["available"])
        self.assertEqual(data["ref_root"], str(ref_root))
        self.assertEqual(data["organisms"], [])

    def test_organism_assembly_with_indexes_and_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "omnibioai-data" / "reference"
            org_path = ref_root / "organisms" / "human" / "GRCh38"
            org_path.mkdir(parents=True)

            idx_path = ref_root / "indexes" / "bwa"
            idx_path.mkdir(parents=True)
            (idx_path / "human.bwt").write_text("x")

            vdb_path = ref_root / "variants" / "human" / "clinvar"
            vdb_path.mkdir(parents=True)
            (vdb_path / "clinvar.vcf").write_text("x")

            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference")
            finally:
                del os.environ["WORKSPACE_ROOT"]

        data = resp.json()
        self.assertTrue(data["available"])
        self.assertEqual(len(data["organisms"]), 1)
        entry = data["organisms"][0]
        self.assertEqual(entry["organism"], "human")
        self.assertEqual(entry["assembly"], "GRCh38")
        self.assertTrue(entry["indexes"]["bwa"])
        self.assertFalse(entry["indexes"]["star"])
        self.assertTrue(entry["variants"]["clinvar"])
        self.assertFalse(entry["variants"]["dbsnp"])

    def test_databases_checked_across_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            db_path = ref_root / "databases" / "gnomad"
            db_path.mkdir(parents=True)
            (db_path / "gnomad.vcf").write_text("x")

            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference")
            finally:
                del os.environ["WORKSPACE_ROOT"]

        data = resp.json()
        self.assertTrue(data["databases"]["gnomad"])
        self.assertFalse(data["databases"]["clinvar"])

    def test_annotation_status_for_human_and_mouse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            ann_path = ref_root / "annotation" / "human" / "gencode"
            ann_path.mkdir(parents=True)
            (ann_path / "gencode.gtf").write_text("x")

            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference")
            finally:
                del os.environ["WORKSPACE_ROOT"]

        data = resp.json()
        self.assertTrue(data["annotation"]["human"]["gencode"])
        self.assertFalse(data["annotation"]["human"]["ensembl"])
        self.assertFalse(data["annotation"]["mouse"]["gencode"])


if __name__ == "__main__":
    unittest.main()
