from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from control_center.core.auth import infra_viewer
from control_center.core.public_view import public_reference

router = APIRouter()

ORGANISMS = {
    "human":      ["GRCh37", "GRCh38", "T2T-CHM13"],
    "mouse":      ["GRCm38", "GRCm39"],
    "rat":        ["GRCr8"],
    "zebrafish":  ["GRCz11"],
    "drosophila": ["BDGP6"],
    "yeast":      ["R64"],
    "chimpanzee": ["Pan_tro_3.0"],
    "macaque":      ["Mmul_10"],
    "celegans":     ["WBcel235"],
    "arabidopsis":  ["TAIR10"],
    "pig":          ["Sscrofa11.1"],
    "chicken":      ["GRCg7b"],
}

INDEXES = ["star", "bwa", "bowtie2", "salmon", "cellranger"]

VARIANT_DBS = ["clinvar", "dbsnp", "gnomad", "cosmic", "gatk_bundle"]

DATABASES = ["clinvar", "cosmic", "dbsnp", "gnomad", "go",
             "interpro", "pfam", "uniprot"]


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


@router.get("/reference")
def get_reference(full: bool = Depends(infra_viewer)) -> JSONResponse:
    data = _reference_status()
    # ref_root is a filesystem path -- operators only (core/public_view.py).
    return JSONResponse(data if full else public_reference(data))


def _reference_status() -> dict:
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    # omnibioai-data is a symlink on host that doesn't resolve in container
    # Try multiple candidate paths
    ref_root = None
    for candidate in [
        workspace / "omnibioai-data" / "reference",
        workspace / "data" / "reference",
    ]:
        if candidate.exists():
            ref_root = candidate
            break

    if ref_root is None:
        return {
            "available": False,
            "ref_root": str(workspace / "omnibioai-data" / "reference"),
            "organisms": [],
            "databases": {},
            "annotation": {},
        }

    organisms = []
    for organism, assemblies in ORGANISMS.items():
        for assembly in assemblies:
            org_path = ref_root / "organisms" / organism / assembly
            if not org_path.exists():
                continue

            index_status = {}
            for idx in INDEXES:
                idx_path = ref_root / "indexes" / idx
                matches = list(idx_path.glob(f"{organism}*")) if idx_path.exists() else []
                index_status[idx] = len(matches) > 0

            variant_status = {}
            for vdb in VARIANT_DBS:
                vdb_path = ref_root / "variants" / organism / vdb
                variant_status[vdb] = _dir_exists_nonempty(vdb_path)

            organisms.append({
                "organism": organism,
                "assembly": assembly,
                "indexes": index_status,
                "variants": variant_status,
            })

    db_status = {}
    for db in DATABASES:
        db_status[db] = any([
            _dir_exists_nonempty(ref_root / "databases" / db),
            _dir_exists_nonempty(ref_root / "variants" / "human" / db),
            _dir_exists_nonempty(ref_root / "variants" / "mouse" / db),
        ])

    annotation_status: dict = {}
    for organism in ["human", "mouse"]:
        annotation_status[organism] = {}
        for source in ["ensembl", "gencode", "refseq", "ucsc"]:
            ann_path = ref_root / "annotation" / organism / source
            annotation_status[organism][source] = _dir_exists_nonempty(ann_path)

    return {
        "available": True,
        "ref_root": str(ref_root),
        "organisms": organisms,
        "databases": db_status,
        "annotation": annotation_status,
    }
