import os
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router_storage = APIRouter()

_CACHE_TTL_SECONDS = 300.0
_storage_cache: tuple[float, dict] | None = None
_storage_refresh: Future[dict] | None = None
_storage_lock = threading.Lock()
_storage_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storage-scan")


def _du(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        result = subprocess.run(
            ["du", "-sb", str(path)],
            capture_output=True, text=True, timeout=60
        )
        return int(result.stdout.split()[0]) if result.returncode == 0 else 0
    except Exception:
        return 0


def _df_disk(path: Path):
    try:
        st = os.statvfs(str(path))
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        return total, used, free
    except Exception:
        return 0, 0, 0


def _compute_storage(workspace: Path) -> dict:
    data_root = None
    for candidate in [workspace / "omnibioai-data", workspace / "data"]:
        if candidate.exists():
            data_root = candidate
            break

    work_root = None
    for candidate in [workspace / "omnibioai-work", workspace / "work"]:
        if candidate.exists():
            work_root = candidate
            break

    total, used, free = _df_disk(workspace)

    categories = {}
    if data_root:
        for name, path in [
            ("Reference Data",    data_root / "reference"),
            ("PubMed / AI Index", data_root / "PubMed"),
            ("Uploads",           data_root / "uploads"),
            ("Objects",           data_root / "objects"),
            ("Datasets",          data_root / "datasets"),
            ("Downloads",         data_root / "downloads"),
        ]:
            size = _du(path)
            if size > 0:
                categories[name] = size

    ref_indexes: dict = {}
    if data_root:
        idx_root = data_root / "reference" / "indexes"
        if idx_root.exists():
            for tool_dir in idx_root.iterdir():
                if tool_dir.is_dir():
                    for org_dir in tool_dir.iterdir():
                        if org_dir.is_dir():
                            size = _du(org_dir)
                            if size > 0:
                                org = org_dir.name
                                ref_indexes[org] = ref_indexes.get(org, 0) + size

    work_breakdown = {}
    if work_root:
        for entry in work_root.iterdir():
            if entry.is_dir():
                size = _du(entry)
                if size > 0:
                    work_breakdown[entry.name] = size

    docker_raw = "unavailable"
    try:
        result = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Size}}"],
            capture_output=True, text=True, timeout=10
        )
        docker_raw = result.stdout.strip()
    except Exception:
        pass

    return {
        "disk": {
            "total": total,
            "used": used,
            "free": free,
            "pct_used": round(used / total * 100, 1) if total > 0 else 0,
        },
        "categories": categories,
        "reference_indexes": ref_indexes,
        "work_breakdown": work_breakdown,
        "docker_raw": docker_raw,
    }


def _storage_snapshot(workspace: Path) -> dict:
    """Return useful storage data without recursively walking the workspace."""
    total, used, free = _df_disk(workspace)
    return {
        "disk": {
            "total": total,
            "used": used,
            "free": free,
            "pct_used": round(used / total * 100, 1) if total > 0 else 0,
        },
        "categories": {},
        "reference_indexes": {},
        "work_breakdown": {},
        "docker_raw": "refreshing",
        "refreshing": True,
    }


def _cached_storage(workspace: Path) -> dict:
    """Serve immediately and refresh expensive directory totals in the background."""
    global _storage_cache, _storage_refresh

    now = time.monotonic()
    with _storage_lock:
        if _storage_refresh is not None and _storage_refresh.done():
            try:
                _storage_cache = (now, _storage_refresh.result())
            except Exception:
                # Retain stale data if an unexpected failure escapes the
                # otherwise defensive scanner.
                pass
            _storage_refresh = None

        cache_is_fresh = (
            _storage_cache is not None
            and now - _storage_cache[0] < _CACHE_TTL_SECONDS
        )
        if not cache_is_fresh and _storage_refresh is None:
            _storage_refresh = _storage_executor.submit(_compute_storage, workspace)

        if _storage_cache is not None:
            return _storage_cache[1]

    return _storage_snapshot(workspace)


@router_storage.get("/storage")
async def get_storage() -> JSONResponse:
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    return JSONResponse(_cached_storage(workspace))
