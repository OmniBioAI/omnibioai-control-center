from __future__ import annotations

import os
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

GHCR_PULL_TOKEN = os.environ.get("GHCR_PULL_TOKEN", "")

_TIMEOUT_S = 5

# Only actual `services:` blocks with a live (uncommented) `:latest` image
# matter here. model-registry/rag/omnibioai(x2)/control-center/
# workflow-bundles/tool-images/web-ui all `build:` from local source instead
# (their `# image:` lines are commented out), and the plugin image list
# further down docker-compose.yml is explicitly documented there as "pulled
# on-demand by TES, not persistent services" -- neither group is a running
# container with a stable digest to compare.
_IMAGES: list[tuple[str, str, str]] = [
    # (service, container name, image ref)
    ("toolserver",      "omnibioai-studio-toolserver-1",      "ghcr.io/omnibioai/omnibioai-toolserver:latest"),
    ("videos",           "omnibioai-studio-videos-1",          "ghcr.io/omnibioai/omnibioai-videos:latest"),
    ("auth-service",     "omnibioai-studio-auth-service-1",    "ghcr.io/omnibioai/omnibioai-auth:latest"),
    ("security-audit",   "omnibioai-studio-security-audit-1",  "ghcr.io/omnibioai/omnibioai-security-audit:latest"),
    ("api-gateway",      "omnibioai-studio-api-gateway-1",     "ghcr.io/omnibioai/omnibioai-api-gateway:latest"),
    ("opa",              "omnibioai-studio-opa-1",             "openpolicyagent/opa:latest"),
    ("prometheus",       "omnibioai-studio-prometheus-1",      "prom/prometheus:latest"),
    ("grafana",          "omnibioai-studio-grafana-1",         "grafana/grafana:latest"),
    ("cadvisor",         "omnibioai-cadvisor",                 "gcr.io/cadvisor/cadvisor:latest"),
    ("redis-exporter",   "omnibioai-redis-exporter",           "oliver006/redis_exporter:latest"),
    ("node-exporter",    "omnibioai-node-exporter",             "prom/node-exporter:latest"),
    ("nginx-router",     "omnibioai-studio-nginx-router-1",    "nginx:latest"),
    ("ollama",           "omnibioai-studio-ollama-1",          "ollama/ollama:latest"),
]

_REGISTRY_AUTH = {
    "ghcr.io":    ("https://ghcr.io/token", "ghcr.io"),
    "docker.io":  ("https://auth.docker.io/token", "registry.docker.io"),
    "gcr.io":     ("https://gcr.io/v2/token", "gcr.io"),
}
_REGISTRY_API_HOST = {
    "docker.io": "registry-1.docker.io",
}
_MANIFEST_ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
])

_ARCH_MAP = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64", "amd64": "amd64"}
_LOCAL_ARCH = _ARCH_MAP.get(platform.machine(), "amd64")


def get_image_freshness() -> dict[str, Any]:
    """Live :latest-vs-running comparison for the /image-freshness endpoint.

    For each service, gets the locally running container's image ID via the
    docker CLI (docker.sock is already mounted) and the registry's published
    :latest digest via that registry's manifest API, then compares them.
    """
    with ThreadPoolExecutor(max_workers=len(_IMAGES)) as pool:
        results = list(pool.map(_check_one, _IMAGES))
    return {"images": [r for r in results if r is not None]}


def _check_one(entry: tuple[str, str, str]) -> Optional[dict[str, Any]]:
    service, container, image = entry
    local_id = _local_image_id(container)
    if local_id is None:
        return None

    registry, repo, tag = _parse_image_ref(image)
    try:
        remote_config_digest, last_pushed = _remote_config_info(registry, repo, tag)
    except Exception:
        remote_config_digest, last_pushed = None, None

    stale = (remote_config_digest is not None) and (local_id != remote_config_digest)
    return {
        "service": service,
        "image": image,
        "stale": stale,
        "last_pushed": last_pushed or "unknown",
    }


def _local_image_id(container: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.Image}}", container],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
        if out.returncode != 0:
            return None
        image_id = out.stdout.strip()
        return image_id.replace("sha256:", "") if image_id else None
    except Exception:
        return None


def _parse_image_ref(image: str) -> tuple[str, str, str]:
    """'ghcr.io/omnibioai/omnibioai-auth:latest' -> ('ghcr.io', 'omnibioai/omnibioai-auth', 'latest')
    'nginx:latest' -> ('docker.io', 'library/nginx', 'latest')
    'prom/prometheus:latest' -> ('docker.io', 'prom/prometheus', 'latest')"""
    name, _, tag = image.rpartition(":")
    name, tag = (name, tag) if name else (image, "latest")
    parts = name.split("/")
    if "." in parts[0] and len(parts) > 1:
        return parts[0], "/".join(parts[1:]), tag
    repo = name if "/" in name else f"library/{name}"
    return "docker.io", repo, tag


def _get_bearer_token(registry: str, repo: str) -> Optional[str]:
    import httpx

    auth_url, service = _REGISTRY_AUTH[registry]
    params = {"service": service, "scope": f"repository:{repo}:pull"}
    auth = ("token", GHCR_PULL_TOKEN) if registry == "ghcr.io" and GHCR_PULL_TOKEN else None
    r = httpx.get(auth_url, params=params, auth=auth, timeout=_TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("token")


def _fetch_manifest(registry: str, repo: str, ref: str, token: str) -> dict:
    import httpx

    api_host = _REGISTRY_API_HOST.get(registry, registry)
    headers = {"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT}
    r = httpx.get(
        f"https://{api_host}/v2/{repo}/manifests/{ref}", headers=headers,
        timeout=_TIMEOUT_S, follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


def _fetch_blob(registry: str, repo: str, digest: str, token: str) -> dict:
    import httpx

    # Registries commonly 307-redirect blob GETs to a signed CDN URL.
    api_host = _REGISTRY_API_HOST.get(registry, registry)
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.get(
        f"https://{api_host}/v2/{repo}/blobs/{digest}", headers=headers,
        timeout=_TIMEOUT_S, follow_redirects=True,
    )
    r.raise_for_status()
    return r.json()


def _remote_config_info(registry: str, repo: str, tag: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (config_digest, created_timestamp). A registry's top-level
    manifest digest is over the manifest JSON itself -- not comparable to a
    local image ID. The manifest's embedded config.digest is (both are the
    digest of the same image-config blob), so that's what we compare against
    the docker-inspect'd local image ID."""
    token = _get_bearer_token(registry, repo)
    manifest = _fetch_manifest(registry, repo, tag, token)

    if "manifests" in manifest:  # multi-arch index/manifest-list
        entry = next(
            (m for m in manifest["manifests"]
             if (m.get("platform") or {}).get("os") == "linux"
             and (m.get("platform") or {}).get("architecture") == _LOCAL_ARCH),
            None,
        )
        if entry is None:
            return None, None
        manifest = _fetch_manifest(registry, repo, entry["digest"], token)

    config_digest = (manifest.get("config") or {}).get("digest")
    if not config_digest:
        return None, None

    created = None
    try:
        config_blob = _fetch_blob(registry, repo, config_digest, token)
        created = config_blob.get("created")
    except Exception:
        pass

    return config_digest.replace("sha256:", ""), created
