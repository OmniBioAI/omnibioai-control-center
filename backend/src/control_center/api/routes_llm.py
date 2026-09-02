from __future__ import annotations
import asyncio
import os
from pathlib import Path
import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from control_center.core.auth import require_permission

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")

@router.get("/llms")
async def get_llms() -> JSONResponse:
    # DELIBERATELY UNAUTHENTICATED. No Depends(require_permission(...)),
    # and llm_router is included in main.py with no router-level gate.
    # This route backs ControlApp's anonymous LLMs page -- see main.py's
    # llm_router include comment and docs/public-control-center.md. The
    # response is boolean-only for secrets: `configured` flags, never key
    # values (see api_keys below). Also called in-process by
    # routes_dashboard.py's _ai_platform_section (a direct function call,
    # unaffected by routing either way).
    # Ollama models
    models = []
    ollama_status = "unreachable"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                ollama_status = "running"
                for m in r.json().get("models", []):
                    models.append({
                        "name": m["name"],
                        "size_gb": round(m.get("size", 0) / 1e9, 1),
                        "modified": m.get("modified_at", "")[:10],
                    })
    except Exception:
        pass

    # API key status — check env vars
    # Never expose actual key values — just whether they are set
    api_keys = {
        "anthropic": {
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "label": "Claude API (Anthropic)",
        },
        "openai": {
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "label": "OpenAI API",
        },
    }

    return JSONResponse({
        "ollama": {
            "status": ollama_status,
            "url": OLLAMA_URL,
            "models": models,
        },
        "api_keys": api_keys,
    })


def _count_json_files(abstracts_dir: Path) -> tuple[int, list[str]]:
    """
    Count unique abstracts (by PMID filename) across domain subdirs.

    A paper is filed under every matching topic domain (e.g. CRISPR_Editing
    is a full subset of CRISPR_GenomeEditing; Alzheimer_Disease and
    Alzheimer_CaseStudy overlap), so the same <pmid>.json exists in multiple
    domain directories. Summing per-domain counts double-counts those papers
    instead of reporting distinct abstracts.
    """
    seen: set[str] = set()
    domains: list[str] = []
    try:
        with os.scandir(abstracts_dir) as top:
            for domain_entry in top:
                if not domain_entry.is_dir():
                    continue
                had_files = False
                try:
                    with os.scandir(domain_entry.path) as inner:
                        for e in inner:
                            if e.is_file() and e.name.endswith(".json"):
                                seen.add(e.name)
                                had_files = True
                except OSError:
                    pass
                if had_files:
                    domains.append(domain_entry.name)
    except OSError:
        pass
    return len(seen), domains


def _list_index_domains(index_root: Path) -> list[str]:
    """List non-empty domain dirs under the index root."""
    domains: list[str] = []
    try:
        with os.scandir(index_root) as top:
            for entry in top:
                if entry.is_dir():
                    try:
                        if any(True for _ in os.scandir(entry.path)):
                            domains.append(entry.name)
                    except OSError:
                        pass
    except OSError:
        pass
    return domains


INDEX_SCRATCH_PREFIXES = ("embedding_checkpoint",)


def _index_size_bytes(index_root: Path) -> int:
    """
    Sum bytes of served index artifacts (pubmed_index.faiss, pmid_map.json, ...)
    under index_root, excluding embedding_checkpoint*.json scratch files.

    Those checkpoints are resumable-embedding progress dumps left behind by the
    indexing run, not part of the queryable index -- and can dwarf it (observed:
    ~322GB of checkpoint JSON vs ~67GB of actual .faiss files across the corpus).
    """
    total = 0
    try:
        with os.scandir(index_root) as top:
            for domain_entry in top:
                if not domain_entry.is_dir():
                    continue
                try:
                    with os.scandir(domain_entry.path) as inner:
                        for e in inner:
                            if not e.is_file() or e.name.startswith(INDEX_SCRATCH_PREFIXES):
                                continue
                            try:
                                total += e.stat().st_size
                            except OSError:
                                pass
                except OSError:
                    pass
    except OSError:
        pass
    return total


@router.get("/knowledge-base")
async def get_knowledge_base(
    _admin: dict = Depends(require_permission("platform.manage_infra")),
) -> JSONResponse:
    # Gated per-route (not via llm_router's include, which is ungated so
    # GET /llms above can stay public). Returns absolute internal
    # filesystem paths (pubmed_root/index_root) -- same platform.manage_infra
    # bar as /summary/docker/config/storage. Commit 8705cbf first added
    # this gate at the router level; the 2026-09-02 investigation moved it
    # here so it no longer also covers /llms.
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))

    pubmed_root = None
    for candidate in [
        workspace / "data" / "PubMed",
        workspace / "omnibioai-data" / "data" / "PubMed",
        workspace / "omnibioai-data" / "PubMed",
    ]:
        if candidate.exists():
            pubmed_root = candidate
            break

    index_root = None
    for candidate in [
        workspace / "data" / "PubMed" / "Index",
        workspace / "data" / "Index",
        workspace / "omnibioai-data" / "data" / "Index",
        workspace / "omnibioai-data" / "Index",
    ]:
        if candidate.exists():
            index_root = candidate
            break

    # Run filesystem scans and RAG health check concurrently
    loop = asyncio.get_event_loop()

    abstracts_dir = (pubmed_root / "Abstracts") if pubmed_root else None

    async def count_abstracts() -> tuple[int, list[str]]:
        if abstracts_dir and abstracts_dir.exists():
            return await loop.run_in_executor(None, _count_json_files, abstracts_dir)
        return 0, []

    async def list_indexed_domains() -> list[str]:
        if index_root and index_root.exists():
            return await loop.run_in_executor(None, _list_index_domains, index_root)
        return []

    async def get_index_size() -> int:
        if index_root and index_root.exists():
            return await loop.run_in_executor(None, _index_size_bytes, index_root)
        return 0

    async def check_rag() -> str:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get("http://rag:8096/health")
                return "running" if r.status_code == 200 else "degraded"
        except Exception:
            return "unreachable"

    (abstract_count, domains_with_abstracts), indexed_domains, index_size_bytes, rag_status = (
        await asyncio.gather(
            count_abstracts(),
            list_indexed_domains(),
            get_index_size(),
            check_rag(),
        )
    )

    return JSONResponse({
        "rag_status": rag_status,
        "abstracts": {
            "total": abstract_count,
            "domains_with_abstracts": len(domains_with_abstracts),
        },
        "faiss_index": {
            "domains_indexed": len(indexed_domains),
            "size_gb": round(index_size_bytes / 1e9, 2),
            "domain_list": sorted(indexed_domains)[:20],
        },
        "pubmed_root": str(pubmed_root) if pubmed_root else None,
        "index_root": str(index_root) if index_root else None,
    })
