"""Read-only Workbench adapter and IH-2 report assembly.

The adapter accepts only an explicit Workbench registry path or plugins root.
It never imports plugin code, reads environment values as credentials, calls
providers, or exposes manifest/source paths.  Configuration and readiness
cache files contain presence/status metadata only and are independently
optional.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from control_center.integration_health import (
    AuthRequirement,
    ConfigurationStatus,
    DataSourceStatus,
    EnabledStatus,
    EvidenceType,
    FailureReason,
    ImplementationStatus,
    IntegrationEvidence,
    IntegrationInventory,
    IntegrationProvider,
    IntegrationRecord,
    ProbeAvailability,
    ProviderStatus,
)


class IntegrationInventoryUnavailable(ValueError):
    """Raised only when the authoritative inventory cannot be built."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MetadataSourceUnavailable(ValueError):
    """Raised for an optional configuration or cache source."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReadinessCache(Protocol):
    def get(self, integration_id: str) -> dict[str, Any] | None: ...


class EmptyReadinessCache:
    def get(self, integration_id: str) -> dict[str, Any] | None:
        return None


_INCLUDED_CATEGORIES = frozenset({"search", "reference_db"})
_HEALTH_SIGNAL = re.compile(r"(?:api_health|health_check)", re.IGNORECASE)
_PLUGIN_LIVENESS = re.compile(r"(?:health_live|health/live)", re.IGNORECASE)
_SAFE_API_TYPES = (("graphql", "GRAPHQL"), ("ftp", "FTP"), ("download", "OBJECT_DOWNLOAD"))
_CATEGORY_BY_PLUGIN = {
    "pubmed_search": "LITERATURE", "ncbi": "GENOMICS", "sra": "GENOMICS", "ena": "GENOMICS", "ucsc": "GENOMICS",
    "dbnsfp": "VARIANT", "dbsnp": "VARIANT", "dbvar": "VARIANT", "dgv": "VARIANT", "gnomad": "VARIANT",
    "gwas_catalog": "VARIANT", "gwas_catalog_search": "VARIANT", "snpedia": "VARIANT",
    "ensembl": "GENE_ANNOTATION", "hgnc": "GENE_ANNOTATION", "mirbase": "GENE_ANNOTATION",
    "biogrid": "PROTEIN", "brenda": "PROTEIN", "cellchat": "PROTEIN", "dip": "PROTEIN", "intact": "PROTEIN",
    "interpro": "PROTEIN", "hpa": "PROTEIN", "pfam": "PROTEIN", "string_db": "PROTEIN", "uniprot": "PROTEIN",
    "pdb_redo": "STRUCTURE", "pdbe": "STRUCTURE", "pdbsum": "STRUCTURE", "rcsb_pdb": "STRUCTURE",
    "kegg": "PATHWAY", "kegg_search": "PATHWAY", "metacyc": "PATHWAY", "reactome": "PATHWAY",
    "hpo": "PHENOTYPE", "phegeni": "PHENOTYPE", "panglaodb": "PHENOTYPE",
    "chembl_search": "DRUG_CHEMISTRY", "drugbank": "DRUG_CHEMISTRY", "drugcentral": "DRUG_CHEMISTRY",
    "opentargets": "DRUG_CHEMISTRY", "pubchem": "DRUG_CHEMISTRY",
    "arrayexpress": "EXPRESSION", "geo_search": "EXPRESSION", "gtex": "EXPRESSION", "metabolights": "EXPRESSION", "pride": "EXPRESSION",
    "encode": "REGULATORY", "jaspar": "REGULATORY", "jaspar_search": "REGULATORY",
    "bioportal": "ONTOLOGY", "gene_ontology": "ONTOLOGY",
    "clingen": "CLINICAL", "clinicaltrials_gov": "CLINICAL", "clinvar": "CLINICAL", "cosmic": "CLINICAL",
    "decipher": "CLINICAL", "disgenet": "CLINICAL", "hgmd": "CLINICAL", "marrvel": "CLINICAL", "omim": "CLINICAL",
    "openfda": "CLINICAL", "orphanet": "CLINICAL", "pharmgkb": "CLINICAL", "pharmvar": "CLINICAL",
    "bionemo": "OTHER", "biostudies": "OTHER",
}


def _read_json(path: Path, *, source: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        raise IntegrationInventoryUnavailable(source) from None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _enum(enum_type, value: Any, default):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return default


def _safe_manifest(data: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise IntegrationInventoryUnavailable(source)
    if any(not isinstance(data.get(key), typ) for key, typ in {
        "slug": str, "name": str, "category": str, "enabled": bool, "version": str,
    }.items()):
        raise IntegrationInventoryUnavailable(source)
    if not re.fullmatch(r"[a-z0-9_]+", data["slug"]):
        raise IntegrationInventoryUnavailable("invalid_id")
    return data


def _source_signal(plugin_dir: Path) -> ProbeAvailability:
    saw_liveness = False
    try:
        files = sorted(plugin_dir.rglob("*.py"))
    except OSError:
        return ProbeAvailability.NO_SAFE_READINESS_SIGNAL
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:1_000_000]
        except OSError:
            continue
        if _HEALTH_SIGNAL.search(text):
            return ProbeAvailability.READY_SIGNAL_EXISTS
        saw_liveness = saw_liveness or bool(_PLUGIN_LIVENESS.search(text))
    return ProbeAvailability.PLUGIN_LIVENESS_ONLY if saw_liveness else ProbeAvailability.NO_SAFE_READINESS_SIGNAL


def _api_type(plugin_dir: Path) -> str:
    try:
        for path in sorted(plugin_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")[:1_000_000].lower()
            for marker, api_type in _SAFE_API_TYPES:
                if marker in text:
                    return api_type
    except OSError:
        pass
    return "REST"


class JsonReadinessCache:
    """Read-only cache reader; no writer is provided in IH-2."""

    def __init__(self, path: Path) -> None:
        payload = _read_json(path, source="readiness_cache_unavailable")
        if not isinstance(payload, dict):
            raise MetadataSourceUnavailable("readiness_cache_invalid")
        self._entries = payload.get("integrations", payload)
        if not isinstance(self._entries, dict):
            raise MetadataSourceUnavailable("readiness_cache_invalid")

    def get(self, integration_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(integration_id)
        if entry is None:
            return None
        if not isinstance(entry, dict):
            return None
        allowed = {"provider_status", "checked_at", "failure_reason", "version", "description"}
        return {key: entry[key] for key in allowed if key in entry}


class WorkbenchIntegrationAdapter:
    """Build records from the current Workbench manifests dynamically."""

    def __init__(self, *, registry_path: Path | None = None, plugins_dir: Path | None = None,
                 configuration: dict[str, dict[str, Any]] | None = None,
                 readiness_cache: ReadinessCache | None = None) -> None:
        self.registry_path = registry_path
        self.plugins_dir = plugins_dir
        self.configuration = configuration or {}
        self.readiness_cache = readiness_cache or EmptyReadinessCache()

    @classmethod
    def from_environment(cls) -> WorkbenchIntegrationAdapter:
        registry = os.environ.get("WORKBENCH_PLUGIN_REGISTRY_PATH")
        plugins = os.environ.get("WORKBENCH_PLUGINS_DIR")
        if not registry and not plugins:
            raise IntegrationInventoryUnavailable("registry_not_configured")
        cache = None
        cache_path = os.environ.get("INTEGRATION_HEALTH_READINESS_CACHE_PATH")
        if cache_path:
            try:
                cache = JsonReadinessCache(Path(cache_path))
            except (IntegrationInventoryUnavailable, MetadataSourceUnavailable):
                cache = EmptyReadinessCache()
        return cls(registry_path=Path(registry) if registry else None,
                   plugins_dir=Path(plugins) if plugins else None, readiness_cache=cache)

    def _manifests(self) -> list[dict[str, Any]]:
        if self.registry_path:
            payload = _read_json(self.registry_path, source="registry_unavailable")
            if not isinstance(payload, list):
                raise IntegrationInventoryUnavailable("registry_invalid")
            return [_safe_manifest(item, source="registry_invalid") for item in payload]
        assert self.plugins_dir is not None
        try:
            paths = sorted(self.plugins_dir.glob("*/plugin.json"))
        except OSError:
            raise IntegrationInventoryUnavailable("registry_unavailable") from None
        if not paths:
            raise IntegrationInventoryUnavailable("registry_empty")
        return [_safe_manifest(_read_json(path, source="registry_unavailable"), source="registry_invalid") for path in paths]

    def _configuration_for(self, integration_id: str) -> tuple[ConfigurationStatus, AuthRequirement, bool | None]:
        entry = self.configuration.get(integration_id, {})
        if not isinstance(entry, dict):
            return ConfigurationStatus.UNKNOWN, AuthRequirement.UNKNOWN, None
        auth = _enum(AuthRequirement, entry.get("auth_requirement"), AuthRequirement.UNKNOWN)
        config = _enum(ConfigurationStatus, entry.get("configuration_status"), ConfigurationStatus.UNKNOWN)
        credential = entry.get("credential_configured") if isinstance(entry.get("credential_configured"), bool) else None
        return config, auth, credential

    def _record(self, manifest: dict[str, Any]) -> IntegrationRecord:
        slug = manifest["slug"]
        category = _CATEGORY_BY_PLUGIN.get(slug, "OTHER")
        plugin_dir = self.plugins_dir / slug if self.plugins_dir else Path()
        signal = _source_signal(plugin_dir) if self.plugins_dir else ProbeAvailability.NO_SAFE_READINESS_SIGNAL
        config_status, auth, credential = self._configuration_for(slug)
        provider = IntegrationProvider(
            name=manifest["name"], api_type=_api_type(plugin_dir) if self.plugins_dir else "UNKNOWN",
            status=ProviderStatus.NOT_CHECKED,
        )
        record = IntegrationRecord(
            integration_id=slug, display_name=manifest["name"], provider=provider,
            category=category, plugin=slug, implementation_status=ImplementationStatus.IMPLEMENTED,
            enabled_status=EnabledStatus.ENABLED if manifest["enabled"] else EnabledStatus.DISABLED,
            configuration_status=config_status, auth_requirement=auth, credential_configured=credential,
            probe_availability=signal, plugin_status="AVAILABLE" if manifest["enabled"] else "DISABLED",
            evidence=(IntegrationEvidence(EvidenceType.PLUGIN_REGISTRY, "AVAILABLE", "Validated Workbench plugin manifest"),),
        )
        cached = self.readiness_cache.get(slug)
        if not cached:
            return record
        status = _enum(ProviderStatus, cached.get("provider_status"), ProviderStatus.UNKNOWN)
        failure = _enum(FailureReason, cached.get("failure_reason"), None)
        if failure is not None and status not in {ProviderStatus.DEGRADED, ProviderStatus.UNAVAILABLE}:
            failure = None
        checked = _parse_datetime(cached.get("checked_at"))
        provider = replace(provider, status=status, failure_reason=failure, last_checked=checked,
                           version=cached.get("version") if isinstance(cached.get("version"), str) else None)
        evidence = record.evidence + (IntegrationEvidence(
            EvidenceType.CACHED_SUCCESS if status is ProviderStatus.AVAILABLE else EvidenceType.PROVIDER_METADATA,
            status.value, "Cached readiness result", checked,
        ),)
        return replace(record, provider=provider, evidence=evidence)

    def build(self) -> IntegrationInventory:
        manifests = self._manifests()
        seen: set[str] = set()
        records: list[IntegrationRecord] = []
        for manifest in manifests:
            if manifest["category"] not in _INCLUDED_CATEGORIES:
                continue
            slug = manifest["slug"]
            if slug in seen:
                raise IntegrationInventoryUnavailable("duplicate_integration_id")
            seen.add(slug)
            records.append(self._record(manifest))
        if not records:
            raise IntegrationInventoryUnavailable("no_included_integrations")
        records.sort(key=lambda record: record.integration_id)
        return IntegrationInventory(tuple(records))


def _load_configuration() -> tuple[dict[str, dict[str, Any]], DataSourceStatus, str | None]:
    path = os.environ.get("INTEGRATION_HEALTH_CONFIGURATION_PATH")
    if not path:
        return {}, DataSourceStatus.NOT_CONFIGURED, None
    try:
        payload = _read_json(Path(path), source="configuration_unavailable")
    except IntegrationInventoryUnavailable:
        return {}, DataSourceStatus.UNAVAILABLE, "configuration_unavailable"
    if not isinstance(payload, dict):
        return {}, DataSourceStatus.UNAVAILABLE, "configuration_invalid"
    entries = payload.get("integrations", payload)
    if not isinstance(entries, dict):
        return {}, DataSourceStatus.UNAVAILABLE, "configuration_invalid"
    return entries, DataSourceStatus.AVAILABLE, None


def build_integration_health_report(*, adapter: WorkbenchIntegrationAdapter | None = None,
                                   generated_at: datetime | None = None) -> dict[str, Any]:
    """Assemble a report without triggering probes."""
    adapter = adapter or WorkbenchIntegrationAdapter.from_environment()
    inventory = adapter.build()
    config, config_status, config_warning = _load_configuration()
    if config:
        adapter = WorkbenchIntegrationAdapter(
            registry_path=adapter.registry_path,
            plugins_dir=adapter.plugins_dir,
            configuration=config,
            readiness_cache=adapter.readiness_cache,
        )
        inventory = adapter.build()
    cache_path = os.environ.get("INTEGRATION_HEALTH_READINESS_CACHE_PATH")
    if not cache_path:
        cache_status = DataSourceStatus.UNKNOWN
    elif isinstance(adapter.readiness_cache, EmptyReadinessCache):
        cache_status = DataSourceStatus.UNAVAILABLE
    else:
        cache_status = DataSourceStatus.AVAILABLE
    try:
        from control_center.regression_health import (
            RegressionHealthUnavailable,
            load_regression_health,
        )
        load_regression_health()
        regression_status = DataSourceStatus.AVAILABLE
    except (OSError, RegressionHealthUnavailable):
        regression_status = DataSourceStatus.UNAVAILABLE
    sources = {
        "plugin_registry": DataSourceStatus.AVAILABLE,
        "configuration": config_status,
        "readiness_cache": cache_status,
        "regression_health": regression_status,
    }
    warnings = list(inventory.warnings)
    if config_warning:
        warnings.append(config_warning)
    return replace(inventory, data_sources=sources, warnings=tuple(warnings)).to_public_dict(
        generated_at=generated_at or datetime.now(UTC)
    )
