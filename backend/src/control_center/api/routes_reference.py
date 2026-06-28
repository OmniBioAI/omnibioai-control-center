from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

ORGANISMS = {
    "human":      ["GRCh37", "GRCh38", "T2T-CHM13"],
    "mouse":      ["GRCm38", "GRCm39"],
    "rat":        ["GRCr8"],
    "zebrafish":  ["GRCz11"],
    "drosophila": ["BDGP6"],
    "yeast":      ["R64"],
}

INDEXES = ["star", "bwa", "bowtie2", "salmon", "cellranger"]

VARIANT_DBS = ["clinvar", "dbsnp", "gnomad", "cosmic", "gatk_bundle"]

DATABASES = ["clinvar", "cosmic", "dbsnp", "gnomad", "go",
             "interpro", "pfam", "uniprot"]


def _dir_exists_nonempty(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return True
    try:
        return any(True for _ in path.iterdir())
    except Exception:
        return False


@router.get("/reference")
def get_reference() -> JSONResponse:
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
        return JSONResponse({
            "available": False,
            "ref_root": str(workspace / "omnibioai-data" / "reference"),
            "organisms": [],
            "databases": {},
            "annotation": {},
        })

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
        db_path = ref_root / "databases" / db
        db_status[db] = _dir_exists_nonempty(db_path)

    annotation_status: dict = {}
    for organism in ["human", "mouse"]:
        annotation_status[organism] = {}
        for source in ["ensembl", "gencode", "refseq", "ucsc"]:
            ann_path = ref_root / "annotation" / organism / source
            annotation_status[organism][source] = _dir_exists_nonempty(ann_path)

    return JSONResponse({
        "available": True,
        "ref_root": str(ref_root),
        "organisms": organisms,
        "databases": db_status,
        "annotation": annotation_status,
    })
