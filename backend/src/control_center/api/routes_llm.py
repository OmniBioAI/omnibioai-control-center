from __future__ import annotations
import asyncio
import os
import struct
from pathlib import Path
from typing import Optional
import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from control_center.core import public_cache
from control_center.core.jwt_verify import TokenInvalid, verify_token

router = APIRouter()


def _has_permission(authorization: Optional[str], permission: str) -> bool:
    """Non-raising counterpart to core.auth.require_permission -- same
    pattern as routes_dashboard.py's own _has_permission (duplicated
    rather than imported, since that one is private to its own module).
    Used only to decide which fields of a response are safe to include,
    never to reject the request outright."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
    except TokenInvalid:
        return False
    return permission in (payload.get("permissions") or [])

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

# The embedding dimension the retrieval service is configured to query
# (mixedbread-ai/mxbai-embed-large-v1 -> 1024 in the deployment config).
# An index built at another dimension cannot be queried until re-embedded.
EXPECTED_EMBEDDING_DIM = int(os.environ.get("RAG_EMBEDDING_DIM", "1024"))
# Counting tens of millions of abstract files is slow; the counts change
# slowly, so they are recomputed at most this often (0 disables caching
# via PUBLIC_CACHE_SECONDS=0, see core/public_cache.py).
KNOWLEDGE_BASE_CACHE_SECONDS = float(os.environ.get("KNOWLEDGE_BASE_CACHE_SECONDS", "3600"))


def _faiss_dimension(path: Path) -> Optional[int]:
    """Vector dimension from a FAISS index file header: 4-byte type code,
    then the dimension as a little-endian int32 (verified against
    faiss.write_index for flat and HNSW indexes). Reads 8 bytes only."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(8)
    except OSError:
        return None
    if len(header) < 8:
        return None
    dim = struct.unpack("<i", header[4:8])[0]
    return dim if dim > 0 else None


def _index_readiness(index_root: Path, expected_dim: int) -> dict:
    """How many domain indexes the retrieval service can query right now:
    an index file at the configured dimension plus its PMID map. Counts
    only -- no domain names or paths."""
    by_dim: dict[str, int] = {}
    total = ready = missing_map = unreadable = 0
    for domain in sorted(_list_index_domains(index_root)):
        total += 1
        domain_dir = index_root / domain
        candidates = sorted(domain_dir.glob("*.faiss"))
        preferred = domain_dir / "pubmed_index.faiss"
        index_file = preferred if preferred in candidates else (candidates[0] if candidates else None)
        dim = _faiss_dimension(index_file) if index_file else None
        if dim is None:
            unreadable += 1
            continue
        by_dim[str(dim)] = by_dim.get(str(dim), 0) + 1
        has_map = any(domain_dir.glob("*pmid_map*"))
        if not has_map:
            missing_map += 1
        elif dim == expected_dim:
            ready += 1
    return {
        "expected_dimension": expected_dim,
        "domains_total": total,
        "domains_ready": ready,
        "domains_by_dimension": by_dim,
        "missing_map": missing_map,
        "unreadable": unreadable,
    }


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
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    # PUBLIC_FIELDS-style split (same pattern as routes_dashboard.py's
    # /dashboard/summary "knowledge" section): this used to be gated
    # per-route behind platform.manage_infra for its *entire* response,
    # because pubmed_root/index_root are absolute internal filesystem
    # paths -- same bar as /summary/docker/config/storage. But that
    # blanket gate also hid the aggregate fields (abstract/domain counts,
    # index size, rag_status) that carry no such sensitivity, which is
    # what broke generate_report.py's unauthenticated fetch (it only ever
    # read the aggregate fields -- see scripts/sections/knowledge_base.py
    # -- and has no way to authenticate itself). Aggregate stats are now
    # always returned; only pubmed_root/index_root stay behind
    # platform.manage_infra, checked below via _has_permission rather
    # than a hard Depends() so the rest of the response survives an
    # absent/insufficient token instead of 401ing outright.
    has_infra_permission = _has_permission(authorization, "platform.manage_infra")

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

    async def get_readiness() -> Optional[dict]:
        if index_root and index_root.exists():
            return await loop.run_in_executor(None, _index_readiness, index_root, EXPECTED_EMBEDDING_DIM)
        return None

    async def scan() -> dict:
        (abstract_count, domains_with_abstracts), indexed_domains, index_size_bytes, readiness = (
            await asyncio.gather(count_abstracts(), list_indexed_domains(), get_index_size(), get_readiness())
        )
        return {
            "abstracts": {
                "total": abstract_count,
                "domains_with_abstracts": len(domains_with_abstracts),
            },
            "faiss_index": {
                "domains_indexed": len(indexed_domains),
                "size_gb": round(index_size_bytes / 1e9, 2),
                "domain_list": sorted(indexed_domains)[:20],
            },
            "readiness": readiness,
        }

    # The filesystem scan is the same for every caller and expensive, so it
    # is cached (core/public_cache.py); the RAG health check stays live.
    counts, rag_status = await asyncio.gather(
        public_cache.cached_async("knowledge_base_scan", scan, ttl=KNOWLEDGE_BASE_CACHE_SECONDS),
        check_rag(),
    )

    return JSONResponse({
        "rag_status": rag_status,
        **counts,
        "pubmed_root": str(pubmed_root) if (pubmed_root and has_infra_permission) else None,
        "index_root": str(index_root) if (index_root and has_infra_permission) else None,
    })
