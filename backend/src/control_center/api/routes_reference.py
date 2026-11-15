"""
OmniBioAI backend.src.control_center.api.routes_reference.

Purpose:
    Defines HTTP route handlers for backend.src.control_center.api.routes_reference, including get_reference.
    Organisms, assemblies, indexes, variant sets and annotation come from the
    contract v1 manifests (organisms/<species>/manifest.yaml); a manifest
    index counts as built only if its sentinel file is also on disk.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from control_center.core import public_cache, reference_manifests
from control_center.core.auth import infra_viewer
from control_center.core.public_view import public_reference

router = APIRouter()

INDEXES = ["star", "bwa", "bowtie2", "salmon", "cellranger"]

# A built index leaves these files at the top of its directory; an empty or
# half-built directory (e.g. a Salmon run that left only twopaco_tmp/) has none.
INDEX_SENTINELS = {
    "star":       ["SA"],
    "bwa":        ["*.bwt"],
    "bowtie2":    ["*.1.bt2", "*.1.bt2l"],
    "salmon":     ["versionInfo.json", "refseq.bin"],
    "cellranger": ["reference.json"],
}

# Tools whose package may sit one directory below the manifest's index path
# (cellranger-8.0.0/gencode_v44/refdata-gex-GRCh38-2024-A/reference.json).
NESTED_SENTINEL_TOOLS = {"cellranger"}

# COSMIC is licensed and never lives in the reference tree (README "Licensed data").
VARIANT_DBS = ["clinvar", "dbsnp", "gnomad", "gatk_bundle"]

SHARED_DATABASES = ["go", "interpro", "pfam", "uniprot"]

ANNOTATION_SOURCES = ["ensembl", "gencode", "refseq", "ucsc"]


def _dir_exists_nonempty(path: Path) -> bool:
    """Return True if path exists and contains at least one file > 0 bytes."""
    if not path.exists():
        return False
    if path.is_file():
        return path.stat().st_size > 0
    try:
        return any(
            f.stat().st_size > 0
            for f in path.rglob("*")
            if f.is_file()
        )
    except Exception:
        return False


def _index_built(index_dir: Path, tool: str) -> bool:
    """Return True if index_dir holds a non-empty sentinel file for tool
    (or is itself one, for an index whose files sit directly in indexes/<tool>/).
    Tools without a known sentinel return True: the manifest status decides."""
    patterns = INDEX_SENTINELS.get(tool)
    if patterns is None:
        return True
    try:
        if index_dir.is_file():
            return index_dir.stat().st_size > 0 and any(
                fnmatch.fnmatch(index_dir.name, p) for p in patterns)
        dirs = [index_dir]
        if tool in NESTED_SENTINEL_TOOLS:
            dirs += [d for d in index_dir.iterdir() if d.is_dir()]
        return any(
            f.is_file() and f.stat().st_size > 0
            for d in dirs
            for pattern in patterns
            for f in d.glob(pattern)
        )
    except Exception:
        return False


@router.get("/reference")
def get_reference(full: bool = Depends(infra_viewer)) -> JSONResponse:
    # ref_root is a filesystem path -- operators only (core/public_view.py).
    if full:
        return JSONResponse(_reference_status())
    return JSONResponse(public_cache.cached("reference", lambda: public_reference(_reference_status())))


def _ref_root_candidates() -> list[Path]:
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    candidates = [workspace / "data" / "reference"]
    env = os.environ.get("OMNIBIOAI_REFERENCE_DATA_DIR")
    if env:
        candidates.insert(0, Path(env))
    return candidates


def _annotation_source(tag: str) -> str:
    """gencode_v46 -> gencode, ensembl_plants_59 -> ensembl, refseq_109.20211119 -> refseq."""
    return tag.split("_", 1)[0]


def _reference_status() -> dict:
    candidates = _ref_root_candidates()
    ref_root = next((c for c in candidates if (c / "organisms").is_dir()), None)

    if ref_root is None:
        return {
            "available": False,
            "ref_root": str(candidates[-1]),
            "organisms": [],
            "databases": {},
            "annotation": {},
        }

    organisms = []
    annotation_status: dict = {}
    variant_sets_present: set[str] = set()
    for species_dir, manifest in reference_manifests.load_manifests(ref_root):
        species = manifest["species"]
        annotation_status[species] = {src: False for src in ANNOTATION_SOURCES}
        for asm_key, asm in (manifest.get("assemblies") or {}).items():
            if not isinstance(asm, dict):
                continue
            files = reference_manifests.open_items(asm.get("files"))
            present_files = [str(f["path"]) for f in files if f.get("status") == "present"]

            index_status = {idx: False for idx in INDEXES}
            for ix in reference_manifests.open_items(asm.get("indexes")):
                tool = str(ix.get("tool") or "")
                built = ix.get("status") == "present" and _index_built(species_dir / str(ix["path"]), tool)
                index_status[tool] = index_status.get(tool, False) or built

            variant_status = {vdb: False for vdb in VARIANT_DBS}
            for path in present_files:
                parts = path.split("/")
                if len(parts) > 3 and parts[1] == "variants":
                    for vdb in VARIANT_DBS:
                        if parts[2].startswith(vdb + "_"):
                            variant_status[vdb] = True
                            variant_sets_present.add(vdb)
                if len(parts) > 3 and parts[1] == "annotation":
                    src = _annotation_source(parts[2])
                    if src in annotation_status[species]:
                        annotation_status[species][src] = True

            organisms.append({
                "organism": species,
                "scientific_name": manifest.get("scientific_name") or species,
                "common_name": manifest.get("common_name") or "",
                "assembly": asm_key,
                "indexes": index_status,
                "variants": variant_status,
            })

    db_status = {vdb: vdb in variant_sets_present for vdb in VARIANT_DBS}
    for db in SHARED_DATABASES:
        db_status[db] = _dir_exists_nonempty(ref_root / "shared" / "databases" / db)

    return {
        "available": True,
        "ref_root": str(ref_root),
        "organisms": organisms,
        "databases": db_status,
        "annotation": annotation_status,
    }
