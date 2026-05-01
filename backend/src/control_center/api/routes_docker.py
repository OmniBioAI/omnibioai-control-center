from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_TOOL_IMAGES_BASE = Path(
    os.environ.get("TOOL_IMAGES_BASE", str(Path.home() / "Desktop/machine/omnibioai-tool-images"))
)
_OMNIBIOAI_BASE = Path(
    os.environ.get("OMNIBIOAI_BASE", str(Path.home() / "Desktop/machine/omnibioai"))
)

_ARCH_RE = re.compile(r"_(arm64|x86_64|amd64|linux|darwin)$", re.IGNORECASE)

_CATEGORIES: dict[str, list[str]] = {
    "alignment":          ["bwa", "star", "hisat", "bowtie", "bismark", "diamond", "minimap", "bbmap"],
    "assembly":           ["flye", "spades", "hifiasm", "megahit", "wtdbg"],
    "variant-calling":    ["bcftools", "gatk", "varscan", "strelka", "deepvariant", "mutect"],
    "rna-seq":            ["deseq2", "edger", "dexseq", "featurecounts", "salmon", "kallisto"],
    "single-cell":        ["cellranger", "doubletfinder", "seurat", "scran"],
    "epigenomics":        ["chromhmm", "epic2", "deeptools", "macs"],
    "protein-structure":  ["alphafold2", "esm2", "autodock", "rosetta"],
    "proteomics":         ["flashlfq", "maxquant", "msfragger"],
    "population-genetics":["admixture", "eigensoft", "beagle", "plink"],
    "annotation":         ["annovar", "augustus", "snpeff", "vep"],
    "metagenomics":       ["bracken", "kraken", "metaphlan", "humann"],
    "qc":                 ["fastqc", "multiqc", "atacqc", "busco", "checkm", "trimmomatic", "fastp"],
    "imaging":            ["cellpose", "fiji", "imagej"],
    "genomics":           ["bedtools", "samtools", "picard", "gatk"],
    "imputation":         ["beagle", "impute", "shapeit"],
}


def _get_category(tool: str) -> str:
    tool_lower = tool.lower()
    for cat, names in _CATEGORIES.items():
        if any(tool_lower.startswith(n) or n in tool_lower for n in names):
            return cat
    return "general"


def _normalize_sif_stem(stem: str) -> str:
    return _ARCH_RE.sub("", stem)


@router.get("/docker/containers")
def get_containers() -> JSONResponse:
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=30,
        )
        containers: list[dict] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        running = sum(
            1 for c in containers
            if c.get("State", "") == "running" or str(c.get("Status", "")).startswith("Up")
        )
        stopped = len(containers) - running
        return JSONResponse({"containers": containers, "running": running, "stopped": stopped})
    except FileNotFoundError:
        return JSONResponse({"error": "docker not found", "containers": [], "running": 0, "stopped": 0}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e), "containers": [], "running": 0, "stopped": 0}, status_code=500)


@router.get("/docker/sif-images")
def get_sif_images() -> JSONResponse:
    dockerfiles_dir = _TOOL_IMAGES_BASE / "dockerfiles"
    sif_dir = _TOOL_IMAGES_BASE / "sif"

    tools: dict[str, dict] = {}

    if dockerfiles_dir.exists():
        for f in sorted(dockerfiles_dir.iterdir()):
            if f.name.startswith("Dockerfile."):
                tool_name = f.name[len("Dockerfile."):]
                tools[tool_name] = {
                    "tool": tool_name,
                    "category": _get_category(tool_name),
                    "sif_path": None,
                    "exists": False,
                    "size_mb": 0.0,
                }

    total_bytes = 0
    if sif_dir.exists():
        for f in sorted(sif_dir.iterdir()):
            if f.suffix == ".sif":
                normalized = _normalize_sif_stem(f.stem)
                size_bytes = f.stat().st_size
                total_bytes += size_bytes
                size_mb = round(size_bytes / (1024 * 1024), 1)
                if normalized in tools:
                    tools[normalized].update({"sif_path": str(f), "exists": True, "size_mb": size_mb})
                elif f.stem in tools:
                    tools[f.stem].update({"sif_path": str(f), "exists": True, "size_mb": size_mb})
                else:
                    tools[normalized] = {
                        "tool": normalized,
                        "category": _get_category(normalized),
                        "sif_path": str(f),
                        "exists": True,
                        "size_mb": size_mb,
                    }

    result = list(tools.values())
    built = sum(1 for t in result if t["exists"])
    missing = len(result) - built
    total_gb = round(total_bytes / (1024 ** 3), 2)

    return JSONResponse({"images": result, "built": built, "missing": missing, "total_gb": total_gb})


@router.get("/docker/plugin-images")
def get_plugin_images() -> JSONResponse:
    images_found: dict[str, dict] = {}
    _IMG_RE = re.compile(
        r'docker_image\s*[=:]\s*["\']?([a-zA-Z0-9._/:-][^\s"\'#,}\]]+)["\']?'
    )

    if _OMNIBIOAI_BASE.exists():
        for ext in ("*.py", "*.yaml", "*.yml"):
            for fpath in _OMNIBIOAI_BASE.rglob(ext):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for match in _IMG_RE.finditer(content):
                    img = match.group(1).strip().rstrip("'\"")
                    if img and "/" in img or ":" in img:
                        plugin = fpath.parent.name
                        if img not in images_found:
                            images_found[img] = {"plugin": plugin, "image": img, "local_status": "unknown"}

    results: list[dict] = []
    for img, info in images_found.items():
        try:
            r = subprocess.run(["docker", "image", "inspect", img], capture_output=True, timeout=10)
            info["local_status"] = "present" if r.returncode == 0 else "missing"
        except Exception:
            info["local_status"] = "unknown"
        results.append(info)

    return JSONResponse({"plugins": results})
