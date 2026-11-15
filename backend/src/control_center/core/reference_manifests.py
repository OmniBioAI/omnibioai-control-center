"""
OmniBioAI backend.src.control_center.core.reference_manifests.

Purpose:
    Read-only access to the reference tree's organism manifests
    (contract v1: <root>/organisms/<species>/manifest.yaml). Same rules as
    omnibioai-workbench plugins/dataset_catalog/reference_manifests.py:
    yaml.safe_load, symlinked species dirs (compat aliases) skipped, a
    manifest whose species is not its directory ignored, licensed_locked
    items never returned, and an mtime-keyed in-process cache.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# manifest path -> ((mtime_ns, size), manifest)
_cache: dict[str, tuple[tuple[int, int], dict[str, Any] | None]] = {}
_cache_lock = threading.Lock()


def is_licensed(item: dict[str, Any]) -> bool:
    return item.get("access") == "licensed_locked" or ("location" in item and "path" not in item)


def open_items(items: Any) -> list[dict[str, Any]]:
    """The dict items of a files/indexes list that have a path and are not licensed."""
    return [i for i in (items or []) if isinstance(i, dict) and i.get("path") and not is_licensed(i)]


def _load(path: Path) -> dict[str, Any] | None:
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(str(path))
        if hit and hit[0] == key:
            return hit[1]
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    manifest = data if isinstance(data, dict) and str(data.get("species") or "") == path.parent.name else None
    if manifest is None:
        logger.warning("reference manifest %s ignored: not a mapping or species does not match its directory", path)
    with _cache_lock:
        _cache[str(path)] = (key, manifest)
    return manifest


def load_manifests(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """(species_dir, manifest) for each organisms/<species>/manifest.yaml, sorted by species.

    Treat the returned manifests as read-only: they are shared with the cache.
    """
    try:
        entries = sorted(os.scandir(root / "organisms"), key=lambda e: e.name)
    except OSError:
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path) / "manifest.yaml"
            if path.is_symlink() or not path.is_file():
                continue
            manifest = _load(path)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("reference manifest under %s skipped: %s", entry.path, exc)
            continue
        if manifest is not None:
            out.append((Path(entry.path), manifest))
    return out


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
