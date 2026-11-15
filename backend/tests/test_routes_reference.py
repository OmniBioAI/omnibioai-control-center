"""
tests/test_routes_reference.py

Unit tests for:
  - control_center.api.routes_reference  (GET /reference)

Covers _dir_exists_nonempty()'s "has real content, not just an empty
directory tree" check, and GET /reference's reading of the contract v1
manifests (organisms/<species>/manifest.yaml) under the reference root:
organism/assembly rows, index status (manifest status plus the tool's
sentinel file), variant sets, shared databases and annotation sources.

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
import yaml

from control_center.api.routes_reference import _dir_exists_nonempty, _index_built
from control_center.core import reference_manifests
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


def _asm(files=(), indexes=()):
    return {"name": "x", "role": "primary", "files": list(files), "indexes": list(indexes), "gaps": []}


def _file(path, status="present"):
    f = {"path": path, "status": status}
    if status == "present":
        f.update(readable=True, size_bytes=1, checksum="pending")
    return f


def _index(tool, version, tag, path, status="present"):
    ix = {"tool": tool, "version": version, "tag": tag, "path": path, "status": status}
    if status == "present":
        ix.update(readable=True, size_bytes=1)
    return ix


HUMAN = {
    "schema_version": 1, "species": "homo_sapiens", "scientific_name": "Homo sapiens",
    "common_name": "Human", "ncbi_taxon_id": 9606,
    "assemblies": {
        "GRCh38": _asm(
            files=[
                _file("GRCh38/genome/GRCh38.primary_assembly.genome.fa.gz"),
                _file("GRCh38/annotation/gencode_v46/gencode.v46.annotation.gtf.gz"),
                _file("GRCh38/annotation/ucsc_hg38/refFlat.txt.gz", status="missing"),
                _file("GRCh38/variants/clinvar_20260621/clinvar.vcf.gz"),
                _file("GRCh38/variants/dbsnp_b157/dbsnp.vcf.gz", status="missing"),
                {"location": "_restricted/licensed/cosmic/v99/CosmicCodingMuts.vcf.gz",
                 "access": "licensed_locked", "status": "present", "readable": False,
                 "size_bytes": 1, "checksum": "not_computed_locked"},
            ],
            indexes=[
                _index("bwa", "unknown", "genome_gencode_primary", "GRCh38/indexes/bwa-unknown/genome_gencode_primary"),
                _index("star", "2.7.11b", "gencode_v46", "GRCh38/indexes/star-2.7.11b/gencode_v46"),
                _index("salmon", "2.1.2", "gencode_v46", "GRCh38/indexes/salmon-2.1.2/gencode_v46", status="missing"),
                _index("cellranger", "8.0.0", "gencode_v44", "GRCh38/indexes/cellranger-8.0.0/gencode_v44"),
            ],
        ),
        "GRCh37": _asm(files=[_file("GRCh37/genome/hg19.fa.gz")]),
    },
}

YEAST = {
    "schema_version": 1, "species": "saccharomyces_cerevisiae", "scientific_name": "Saccharomyces cerevisiae",
    "common_name": "Yeast (S288C)", "ncbi_taxon_id": 559292,
    "assemblies": {"R64-1-1": _asm(
        files=[_file("R64-1-1/annotation/ensembl_112/Saccharomyces_cerevisiae.R64-1-1.112.gtf.gz")],
        indexes=[_index("bowtie2", "unknown", "genome_ensembl_112_toplevel",
                        "R64-1-1/indexes/bowtie2-unknown/genome_ensembl_112_toplevel")],
    )},
}


class _RefTree(unittest.TestCase):
    """Builds a temp WORKSPACE_ROOT/data/reference tree for each test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.ref_root = Path(self.tmp) / "data" / "reference"
        self._env = patch.dict(os.environ, {"WORKSPACE_ROOT": self.tmp})
        self._env.start()
        os.environ.pop("OMNIBIOAI_REFERENCE_DATA_DIR", None)
        reference_manifests.clear_cache()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()
        reference_manifests.clear_cache()

    def manifest(self, manifest: dict) -> Path:
        d = self.ref_root / "organisms" / manifest["species"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        return d

    def touch(self, rel: str, data: bytes = b"x") -> None:
        p = self.ref_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, headers=None) -> dict:
        return client.get("/reference", headers=headers or _infra_headers).json()

    def rows(self) -> dict:
        return {(o["organism"], o["assembly"]): o for o in self.get()["organisms"]}


class TestGetReference(_RefTree):
    """GET /reference reads the organism manifests."""

    def test_no_ref_root_returns_unavailable(self) -> None:
        """With no reference root at all, available is False and everything is empty."""
        data = self.get()
        self.assertFalse(data["available"])
        self.assertEqual(data["organisms"], [])
        self.assertEqual(data["databases"], {})
        self.assertEqual(data["annotation"], {})

    def test_ref_root_via_data_reference(self) -> None:
        """data/reference with an organisms/ dir is available; operators see ref_root."""
        (self.ref_root / "organisms").mkdir(parents=True)
        data = self.get()
        self.assertTrue(data["available"])
        self.assertEqual(data["ref_root"], str(self.ref_root))
        self.assertEqual(data["organisms"], [])

    def test_root_without_organisms_is_unavailable(self) -> None:
        """An empty or unmounted data/reference (no organisms/) is reported unavailable."""
        self.ref_root.mkdir(parents=True)
        self.assertFalse(self.get()["available"])

    def test_ref_root_from_env_wins(self) -> None:
        """OMNIBIOAI_REFERENCE_DATA_DIR is tried before WORKSPACE_ROOT/data/reference."""
        other = Path(self.tmp) / "elsewhere"
        (other / "organisms").mkdir(parents=True)
        (self.ref_root / "organisms").mkdir(parents=True)
        with patch.dict(os.environ, {"OMNIBIOAI_REFERENCE_DATA_DIR": str(other)}):
            self.assertEqual(self.get()["ref_root"], str(other))

    def test_anonymous_caller_gets_no_ref_root(self) -> None:
        """The public view hides the filesystem path, available or not."""
        missing = client.get("/reference").json()
        (self.ref_root / "organisms").mkdir(parents=True)
        present = client.get("/reference").json()
        for data in (missing, present):
            self.assertNotIn("ref_root", data)
            self.assertNotIn(self.tmp, str(data))

    def test_one_row_per_manifest_assembly(self) -> None:
        """Each species/assembly in the manifests is a row, with its common name."""
        self.manifest(HUMAN)
        self.manifest(YEAST)
        rows = self.rows()
        self.assertEqual(set(rows), {("homo_sapiens", "GRCh38"), ("homo_sapiens", "GRCh37"),
                                     ("saccharomyces_cerevisiae", "R64-1-1")})
        self.assertEqual(rows[("homo_sapiens", "GRCh38")]["common_name"], "Human")

    def test_legacy_dirs_without_manifest_are_not_listed(self) -> None:
        """Old organisms/human/GRCh38 and indexes/<tool>/ shapes no longer count."""
        (self.ref_root / "organisms" / "human" / "GRCh38").mkdir(parents=True)
        self.touch("indexes/bwa/human.bwt")
        self.touch("variants/human/clinvar/clinvar.vcf")
        self.assertEqual(self.get()["organisms"], [])

    def test_symlinked_species_dir_skipped(self) -> None:
        """A compat alias organisms/yeast -> saccharomyces_cerevisiae is not listed twice."""
        self.manifest(YEAST)
        (self.ref_root / "organisms" / "yeast").symlink_to("saccharomyces_cerevisiae")
        self.assertEqual([o["organism"] for o in self.get()["organisms"]], ["saccharomyces_cerevisiae"])

    def test_index_needs_manifest_present_and_sentinel(self) -> None:
        """bwa: present + .bwt -> True; star: present but no SA -> False; salmon: missing -> False."""
        d = self.manifest(HUMAN)
        (d / "GRCh38/indexes/bwa-unknown/genome_gencode_primary").mkdir(parents=True)
        (d / "GRCh38/indexes/bwa-unknown/genome_gencode_primary/genome.fa.gz.bwt").write_bytes(b"x")
        (d / "GRCh38/indexes/star-2.7.11b/gencode_v46").mkdir(parents=True)
        (d / "GRCh38/indexes/star-2.7.11b/gencode_v46/Log.out").write_bytes(b"x")
        (d / "GRCh38/indexes/salmon-2.1.2/gencode_v46").mkdir(parents=True)
        (d / "GRCh38/indexes/salmon-2.1.2/gencode_v46/versionInfo.json").write_bytes(b"x")
        idx = self.rows()[("homo_sapiens", "GRCh38")]["indexes"]
        self.assertTrue(idx["bwa"])
        self.assertFalse(idx["star"])
        self.assertFalse(idx["salmon"])
        self.assertFalse(idx["bowtie2"])

    def test_sentinel_alone_does_not_make_present(self) -> None:
        """An index on disk that the manifest does not list as present is not reported."""
        d = self.manifest(HUMAN)
        (d / "GRCh38/indexes/salmon-2.1.2/gencode_v46").mkdir(parents=True)
        (d / "GRCh38/indexes/salmon-2.1.2/gencode_v46/refseq.bin").write_bytes(b"x")
        self.assertFalse(self.rows()[("homo_sapiens", "GRCh38")]["indexes"]["salmon"])

    def test_cellranger_package_one_level_down(self) -> None:
        """The extracted Cell Ranger package sits in a subdir of the manifest's index path."""
        d = self.manifest(HUMAN)
        pkg = d / "GRCh38/indexes/cellranger-8.0.0/gencode_v44/refdata-gex-GRCh38-2024-A"
        pkg.mkdir(parents=True)
        (pkg / "reference.json").write_bytes(b"{}")
        self.assertTrue(self.rows()[("homo_sapiens", "GRCh38")]["indexes"]["cellranger"])

    def test_nested_sentinel_only_for_cellranger(self) -> None:
        """A STAR SA one level down does not count: STAR's sentinel must be at the top."""
        d = self.manifest(HUMAN)
        (d / "GRCh38/indexes/star-2.7.11b/gencode_v46/sub").mkdir(parents=True)
        (d / "GRCh38/indexes/star-2.7.11b/gencode_v46/sub/SA").write_bytes(b"x")
        self.assertFalse(self.rows()[("homo_sapiens", "GRCh38")]["indexes"]["star"])

    def test_variants_from_manifest_sets(self) -> None:
        """clinvar_20260621 present -> clinvar True; dbsnp_b157 missing -> False; no cosmic key."""
        self.manifest(HUMAN)
        data = self.get()
        v = {(o["organism"], o["assembly"]): o for o in data["organisms"]}[("homo_sapiens", "GRCh38")]["variants"]
        self.assertTrue(v["clinvar"])
        self.assertFalse(v["dbsnp"])
        self.assertNotIn("cosmic", v)
        self.assertTrue(data["databases"]["clinvar"])
        self.assertFalse(data["databases"]["dbsnp"])
        self.assertNotIn("cosmic", data["databases"])

    def test_licensed_items_never_reported(self) -> None:
        """A licensed_locked item leaves no trace in the response."""
        self.manifest(HUMAN)
        self.assertNotIn("cosmic", str(self.get()).lower())
        self.assertNotIn("_restricted", str(self.get()))

    def test_shared_databases(self) -> None:
        """go/interpro/pfam/uniprot are read from shared/databases/<db>/."""
        (self.ref_root / "organisms").mkdir(parents=True)
        self.touch("shared/databases/go/go-basic.obo")
        self.touch("shared/databases/uniprot/swissprot/uniprot_sprot.fasta.gz")
        (self.ref_root / "shared/databases/pfam").mkdir(parents=True)
        db = self.get()["databases"]
        self.assertTrue(db["go"])
        self.assertTrue(db["uniprot"])
        self.assertFalse(db["pfam"])
        self.assertFalse(db["interpro"])

    def test_annotation_sources_per_species(self) -> None:
        """Annotation tags map to sources; only present files count."""
        self.manifest(HUMAN)
        self.manifest(YEAST)
        ann = self.get()["annotation"]
        self.assertTrue(ann["homo_sapiens"]["gencode"])
        self.assertFalse(ann["homo_sapiens"]["ucsc"])
        self.assertFalse(ann["homo_sapiens"]["ensembl"])
        self.assertTrue(ann["saccharomyces_cerevisiae"]["ensembl"])

    def test_broken_manifest_skipped(self) -> None:
        """Invalid YAML for one species does not hide the others."""
        self.manifest(YEAST)
        d = self.ref_root / "organisms" / "homo_sapiens"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text("assemblies: [unclosed", encoding="utf-8")
        self.assertEqual([o["organism"] for o in self.get()["organisms"]], ["saccharomyces_cerevisiae"])

    def test_non_mapping_assembly_skipped(self) -> None:
        """An assembly entry that is not a mapping is ignored, not an error."""
        self.manifest({**YEAST, "assemblies": {**YEAST["assemblies"], "broken": "not a mapping"}})
        self.assertEqual([o["assembly"] for o in self.get()["organisms"]], ["R64-1-1"])

    def test_load_manifests_missing_root(self) -> None:
        """load_manifests() on a root without organisms/ returns nothing."""
        self.assertEqual(reference_manifests.load_manifests(Path(self.tmp) / "absent"), [])

    def test_species_mismatch_skipped(self) -> None:
        """A manifest in the wrong species dir is ignored."""
        d = self.ref_root / "organisms" / "mus_musculus"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text(yaml.safe_dump(YEAST), encoding="utf-8")
        self.assertEqual(self.get()["organisms"], [])


class TestIndexSentinels(unittest.TestCase):
    """_index_built(): a directory counts only when it holds the tool's
    non-empty sentinel file (CC #134), checked on the manifest's index path."""

    BUILT = {
        "star":       "SA",
        "bwa":        "genome.fa.gz.bwt",
        "bowtie2":    "genome.1.bt2",
        "salmon":     "versionInfo.json",
        "cellranger": "reference.json",
    }

    def test_empty_dir_is_not_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for tool in self.BUILT:
                with self.subTest(tool=tool):
                    self.assertFalse(_index_built(Path(tmp), tool))

    def test_sentinel_marks_built(self) -> None:
        for tool, sentinel in self.BUILT.items():
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / sentinel).write_bytes(b"x")
                self.assertTrue(_index_built(Path(tmp), tool))

    def test_half_built_salmon_is_not_built(self) -> None:
        """A failed Salmon build leaves twopaco_tmp/ and logs but no versionInfo.json or refseq.bin."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "twopaco_tmp").mkdir()
            (Path(tmp) / "twopaco_tmp" / "candidate_0.tmp").write_bytes(b"x")
            (Path(tmp) / "pre_indexing.log").write_bytes(b"x")
            self.assertFalse(_index_built(Path(tmp), "salmon"))

    def test_zero_byte_sentinel_is_not_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "SA").write_bytes(b"")
            self.assertFalse(_index_built(Path(tmp), "star"))

    def test_bowtie2_large_index_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "genome.1.bt2l").write_bytes(b"x")
            self.assertTrue(_index_built(Path(tmp), "bowtie2"))

    def test_sentinel_file_given_directly(self) -> None:
        """An index path that is itself the sentinel file counts; any other file does not."""
        with tempfile.TemporaryDirectory() as tmp:
            bwt = Path(tmp) / "genome.bwt"
            bwt.write_bytes(b"x")
            other = Path(tmp) / "genome.pac"
            other.write_bytes(b"x")
            self.assertTrue(_index_built(bwt, "bwa"))
            self.assertFalse(_index_built(other, "bwa"))

    def test_missing_dir_is_not_built(self) -> None:
        self.assertFalse(_index_built(Path("/nonexistent/index"), "star"))

    def test_glob_exception_is_not_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "glob", side_effect=OSError("boom")):
                self.assertFalse(_index_built(Path(tmp), "star"))

    def test_unknown_tool_defers_to_manifest(self) -> None:
        """A tool with no known sentinel is not second-guessed."""
        self.assertTrue(_index_built(Path("/nonexistent"), "hisat2"))


if __name__ == "__main__":
    unittest.main()
