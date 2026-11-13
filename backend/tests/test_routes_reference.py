"""
tests/test_routes_reference.py

Unit tests for:
  - control_center.api.routes_reference  (GET /reference)

Covers _dir_exists_nonempty()'s "has real content, not just an empty
directory tree" check, and GET /reference's discovery of organism/
assembly index and variant-DB presence, cross-location database checks,
and per-organism annotation status, under the reference root (data/reference).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import jwt

from control_center.api.routes_reference import _dir_exists_nonempty, _index_built
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
_infra_headers = {"Authorization": f"Bearer {_INFRA_TOKEN}"}


class TestDirExistsNonempty(unittest.TestCase):
    """_dir_exists_nonempty()'s "has real, non-empty content" check for
    both a file path and a directory tree."""

    def test_missing_path_is_false(self) -> None:
        """A path that doesn't exist returns False."""
        self.assertFalse(_dir_exists_nonempty(Path("/nonexistent/path/xyz")))

    def test_file_with_content_is_true(self) -> None:
        """A file with non-empty content returns True."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "data.txt"
            f.write_text("hello")
            self.assertTrue(_dir_exists_nonempty(f))

    def test_empty_file_is_false(self) -> None:
        """A zero-byte file returns False."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "empty.txt"
            f.write_text("")
            self.assertFalse(_dir_exists_nonempty(f))

    def test_dir_with_nonempty_file_is_true(self) -> None:
        """A directory containing at least one non-empty file (nested or
        not) returns True."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "sub"
            d.mkdir()
            (d / "x.txt").write_text("content")
            self.assertTrue(_dir_exists_nonempty(Path(tmp)))

    def test_dir_with_only_empty_files_is_false(self) -> None:
        """A directory whose only file is zero-byte returns False."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty.txt").write_text("")
            self.assertFalse(_dir_exists_nonempty(Path(tmp)))

    def test_empty_dir_is_false(self) -> None:
        """A directory with no files at all returns False."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_dir_exists_nonempty(Path(tmp)))

    def test_rglob_exception_is_false(self) -> None:
        """An exception raised while scanning the directory returns
        False rather than propagating."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "rglob", side_effect=OSError("boom")):
                self.assertFalse(_dir_exists_nonempty(Path(tmp)))


class TestGetReference(unittest.TestCase):
    """GET /reference's discovery of organism/assembly indexes and
    variant DBs, cross-location database checks, and per-organism
    annotation status."""

    def test_no_ref_root_returns_unavailable(self) -> None:
        """With no reference root directory present at all, available
        is False and organisms/databases/annotation are all empty."""
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
        """An existing data/reference directory (even empty of
        organisms) is discovered as available; an operator
        (platform.manage_infra) also sees the ref_root path."""
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            ref_root.mkdir(parents=True)
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference", headers=_infra_headers)
            finally:
                del os.environ["WORKSPACE_ROOT"]
        data = resp.json()
        self.assertTrue(data["available"])
        self.assertEqual(data["ref_root"], str(ref_root))
        self.assertEqual(data["organisms"], [])

    def test_anonymous_caller_gets_no_ref_root(self) -> None:
        """The public dashboard sees availability and index status but not
        the filesystem path, in either the available or unavailable case."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                missing = client.get("/reference").json()
                (Path(tmp) / "data" / "reference").mkdir(parents=True)
                present = client.get("/reference").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        for data in (missing, present):
            self.assertNotIn("ref_root", data)
            self.assertNotIn(tmp, str(data))
        self.assertFalse(missing["available"])
        self.assertTrue(present["available"])

    def test_organism_assembly_with_indexes_and_variants(self) -> None:
        """A reference root under data/reference reports the organism/
        assembly and correctly distinguishes
        which index type (bwa present, star absent) and which variant DB
        (clinvar present, dbsnp absent) actually has content."""
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
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
        """A populated gnomad database directory is reported present,
        while an unpopulated clinvar database is reported absent."""
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
        """A populated human/gencode annotation directory is reported
        present, while human/ensembl and mouse/gencode (both absent)
        are reported false."""
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


class TestIndexSentinels(unittest.TestCase):
    """An index directory counts as present only when it holds the tool's
    sentinel file; an empty or half-built directory does not."""

    BUILT = {
        "star":       ("human_GRCh38_gencode46", "SA"),
        "bwa":        ("human_GRCh38", "human_GRCh38.bwt"),
        "bowtie2":    ("human_GRCh38", "human_GRCh38.1.bt2"),
        "salmon":     ("human_GRCh38_gencode46", "versionInfo.json"),
        "cellranger": ("human_2024-A", "reference.json"),
    }

    def _status(self, layout) -> dict:
        """Build layout {relative path: bytes or None for a dir} under a
        temp data/reference and return GET /reference's human/GRCh38 indexes."""
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            (ref_root / "organisms" / "human" / "GRCh38").mkdir(parents=True)
            for rel, data in layout.items():
                p = ref_root / rel
                if data is None:
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/reference", headers=_infra_headers)
            finally:
                del os.environ["WORKSPACE_ROOT"]
        return resp.json()["organisms"][0]["indexes"]

    def test_empty_index_directories_are_not_present(self) -> None:
        """The live tree has empty indexes/star/human_GRCh38_gencode46 and
        similar directories; they must not show as prepared indexes."""
        layout = {f"indexes/{tool}/{d}": None for tool, (d, _) in self.BUILT.items()}
        self.assertEqual(self._status(layout), {tool: False for tool in self.BUILT})

    def test_sentinel_file_marks_each_index_present(self) -> None:
        """Each tool's sentinel file, non-empty, marks its index present."""
        for tool, (d, sentinel) in self.BUILT.items():
            with self.subTest(tool=tool):
                status = self._status({f"indexes/{tool}/{d}/{sentinel}": b"x"})
                self.assertTrue(status[tool])
                self.assertFalse(any(v for k, v in status.items() if k != tool))

    def test_half_built_salmon_is_not_present(self) -> None:
        """A failed Salmon build leaves twopaco_tmp/ and logs but no
        versionInfo.json or refseq.bin."""
        status = self._status({
            "indexes/salmon/human_GRCh38_gencode46/twopaco_tmp/candidate_0.tmp": b"x",
            "indexes/salmon/human_GRCh38_gencode46/pre_indexing.log": b"x",
            "indexes/salmon/human_GRCh38_gencode46/ref_k31_fixed.fa": b"x",
        })
        self.assertFalse(status["salmon"])

    def test_star_log_only_is_not_present(self) -> None:
        """A STAR run that stopped early leaves Log.out but no SA."""
        status = self._status({"indexes/star/human_GRCh38_gencode46/Log.out": b"x"})
        self.assertFalse(status["star"])

    def test_zero_byte_sentinel_is_not_present(self) -> None:
        """A zero-byte sentinel (failed download or truncated write) does not count."""
        status = self._status({"indexes/star/human_GRCh38_gencode46/SA": b""})
        self.assertFalse(status["star"])

    def test_glob_exception_is_not_present(self) -> None:
        """An exception raised while scanning an index directory reports the
        index as absent rather than propagating."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "glob", side_effect=OSError("boom")):
                self.assertFalse(_index_built(Path(tmp), "star"))

    def test_bowtie2_large_index_counts(self) -> None:
        """Bowtie2 large indexes use .bt2l."""
        status = self._status({"indexes/bowtie2/human_GRCh38/human_GRCh38.1.bt2l": b"x"})
        self.assertTrue(status["bowtie2"])

    def test_index_reached_through_a_relative_symlink(self) -> None:
        """After the contract v1 reorganisation, indexes/<tool>/<legacy> is a
        relative symlink into organisms/<species>/<assembly>/indexes/."""
        with tempfile.TemporaryDirectory() as tmp:
            ref_root = Path(tmp) / "data" / "reference"
            (ref_root / "organisms" / "human" / "GRCh38").mkdir(parents=True)
            real = ref_root / "organisms/homo_sapiens/GRCh38/indexes/star-2.7.11b/gencode_v46"
            real.mkdir(parents=True)
            (real / "SA").write_bytes(b"x")
            (ref_root / "indexes" / "star").mkdir(parents=True)
            (ref_root / "indexes/star/human_GRCh38_gencode46").symlink_to(
                "../../organisms/homo_sapiens/GRCh38/indexes/star-2.7.11b/gencode_v46")
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                data = client.get("/reference", headers=_infra_headers).json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertTrue(data["organisms"][0]["indexes"]["star"])


if __name__ == "__main__":
    unittest.main()
