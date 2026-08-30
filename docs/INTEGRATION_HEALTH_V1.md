# Integration Health V1 — discovery and readiness contract

Status: IH-1 discovery/model, IH-2 backend adapter/protected API, and IH-3.1
bounded live P0 validation. No frontend, plugin manifest change, credential
change, or upstream repository change is included.

## Scope and inclusion rule

Integration Health covers a Workbench plugin when its source contains a
provider-facing biological/data connector: the Workbench `search` and
`reference_db` categories. The source inventory contains 7 search and 60
reference-db plugins, all enabled in the checked-in registry. Scientific
analysis, workflow, AI, utility, and dashboard plugins are excluded even when
they consume an integration indirectly. Action-capable external platforms
(the 36 Workbench `integration` category plugins) are a separate future
inventory; they are not biological/data provider integrations and are not
silently mixed into this V1 count.

The existing Control Center `/integrations` page is separate: it reports
environment-variable presence for Sentry and two Discord webhook targets.
It does not report Workbench provider reachability and must not be used as
plugin health evidence.

## Plugin architecture and complete source inventory

Workbench discovers `plugins/*/plugin.json`, validates it through
`plugins/registry.py`, and compiles metadata to `plugin_registry.json` and
enabled Django apps to `compiled_apps.py`. A disabled manifest is not mounted;
the checked-in source currently has 351 manifests and zero disabled entries.
Each inventory row below is therefore an actual source manifest, not a name
mentioned only in documentation. `provider` and normalized `category` are
discovery mappings, not claims of current reachability.

| Plugin | Provider | Category |
|---|---|---|
| arrayexpress | ArrayExpress | EXPRESSION |
| biogrid | BioGRID | PROTEIN |
| bionemo | BioNeMo | OTHER |
| bioportal | BioPortal | ONTOLOGY |
| biostudies | BioStudies | OTHER |
| brenda | BRENDA | PROTEIN |
| cellchat | CellChat | EXPRESSION |
| chembl_search | ChEMBL | DRUG_CHEMISTRY |
| clingen | ClinGen | CLINICAL |
| clinicaltrials_gov | ClinicalTrials.gov | CLINICAL |
| clinvar | NCBI ClinVar | CLINICAL |
| cosmic | COSMIC | CLINICAL |
| dbnsfp | dbNSFP | VARIANT |
| dbsnp | NCBI dbSNP | VARIANT |
| dbvar | NCBI dbVar | VARIANT |
| decipher | DECIPHER | CLINICAL |
| dgv | DGV | VARIANT |
| dip | DIP | PROTEIN |
| disgenet | DisGeNET | CLINICAL |
| drugbank | DrugBank | DRUG_CHEMISTRY |
| drugcentral | DrugCentral | DRUG_CHEMISTRY |
| ena | ENA | GENOMICS |
| encode | ENCODE | REGULATORY |
| ensembl | Ensembl | GENE_ANNOTATION |
| gene_ontology | Gene Ontology | ONTOLOGY |
| geo_search | NCBI GEO | EXPRESSION |
| gnomad | gnomAD | VARIANT |
| gtex | GTEx | EXPRESSION |
| gwas_catalog | NHGRI-EBI GWAS Catalog | VARIANT |
| gwas_catalog_search | NHGRI-EBI GWAS Catalog | VARIANT |
| hgmd | HGMD | CLINICAL |
| hgnc | HGNC | GENE_ANNOTATION |
| hpa | Human Protein Atlas | PROTEIN |
| hpo | HPO | PHENOTYPE |
| intact | IntAct | PROTEIN |
| interpro | InterPro | PROTEIN |
| jaspar | JASPAR | REGULATORY |
| jaspar_search | JASPAR | REGULATORY |
| kegg | KEGG | PATHWAY |
| kegg_search | KEGG | PATHWAY |
| marrvel | MARRVEL | CLINICAL |
| metabolights | MetaboLights | EXPRESSION |
| metacyc | MetaCyc | PATHWAY |
| mirbase | miRBase | GENE_ANNOTATION |
| ncbi | NCBI E-utilities | GENOMICS |
| omim | OMIM | CLINICAL |
| openfda | OpenFDA | CLINICAL |
| opentargets | Open Targets | DRUG_CHEMISTRY |
| orphanet | Orphanet | CLINICAL |
| panglaodb | PanglaoDB | EXPRESSION |
| pdb_redo | PDB-REDO | STRUCTURE |
| pdbe | PDBe | STRUCTURE |
| pdbsum | PDBsum | STRUCTURE |
| pfam | Pfam | PROTEIN |
| pharmgkb | PharmGKB | CLINICAL |
| pharmvar | PharmVar | CLINICAL |
| phegeni | PheGenI | PHENOTYPE |
| pride | PRIDE | EXPRESSION |
| pubchem | NCBI PubChem | DRUG_CHEMISTRY |
| pubmed_search | NCBI PubMed | LITERATURE |
| rcsb_pdb | RCSB PDB | STRUCTURE |
| reactome | Reactome | PATHWAY |
| snpedia | SNPedia | VARIANT |
| sra | NCBI SRA | GENOMICS |
| string_db | STRING | PROTEIN |
| ucsc | UCSC Genome Browser | GENOMICS |
| uniprot | UniProt | PROTEIN |

API types are mixed REST, GraphQL, FTP/object download, and custom/mixed
clients. Canonical public endpoint families are documented in each plugin's
README/client; the future response should expose family/provider/version only,
never arbitrary URLs, proxy URLs, or internal paths. The source knows explicit
versions/releases for some providers (for example Ensembl, gnomAD, Reactome,
RCSB/PDBe, STRING, and miRBase); it does not know a single uniform version for
the inventory and V1 must emit null/unknown when source/configuration has none.

## State, evidence, and readiness

The pure model in `backend/src/control_center/integration_health.py` keeps
implementation, enabled state, configuration, provider state, readiness,
freshness, tests, and certification separate. There is intentionally no
numeric health score.

Readiness is deterministic:

* disabled → `DISABLED`;
* not implemented → `NOT_READY`;
* enabled with no provider evidence → `UNKNOWN`; unknown configuration metadata
  does not override an explicit provider result;
* required credentials missing, or configuration incomplete → `NOT_READY`;
* configured/public + provider available → `READY`;
* provider degraded (including evidenced rate limiting) → `DEGRADED`;
* provider unavailable → `NOT_READY`;
* provider not checked/unknown → `UNKNOWN`.

Provider unavailability is an integration state, not a platform/deployment
failure. Plugin liveness only proves loaded code; it never proves readiness.

Evidence is allowlisted as registry, configuration, plugin test, live probe,
regression certification, provider metadata, cached success, or configuration.
Each item has only source/status/timestamp/short description. Test and
regression certification remain independent from current provider status: a
certified integration can be unavailable, and an available one can be
uncertified. The existing regression artifact certifies platform capabilities
(including a representative JASPAR plugin lifecycle), not an integration-level
mapping; that mapping is a documented gap.

Freshness is `CURRENT` or `STALE` from an actual `last_checked` timestamp and a
bounded policy TTL, otherwise `UNKNOWN`. A unit test timestamp must not be
presented as provider freshness.

Authentication is metadata only: `PUBLIC`, `OPTIONAL_AUTH`,
`AUTH_REQUIRED`, or `UNKNOWN`, plus nullable `credential_configured`. No key,
token, password, header, cookie, or environment value is ever modeled or
serialized.

Failure classes are NETWORK, TIMEOUT, DNS, AUTHENTICATION, AUTHORIZATION,
RATE_LIMIT, PROVIDER_5XX, INVALID_RESPONSE, SCHEMA_MISMATCH, CONFIGURATION,
DISABLED, and UNKNOWN. A `429`/Retry-After becomes rate-limited only when the
provider client exposes that evidence; it is never triggered for discovery.

## Readiness signal inventory and future probes

Static inspection found 49 provider-facing plugins with an explicit
`api_health`/`health_check` contract. Ten have only plugin liveness, and eight
have no health match. The latter two groups need a provider-specific review:
small read-only probes are a possible P1 contract for clients with a safe
metadata endpoint; object-download-only or otherwise expensive connectors have
`NO_SAFE_READINESS_SIGNAL` until an upstream contract exists. IH-3.1 performed
one bounded live request for each approved P0 definition; the results below are
point-in-time evidence and are not a permanent provider availability claim.

Any future probe must use a static allowlist of provider hosts/path families,
GET/read-only semantics, bounded connect/read/total timeouts, a small response,
no workload/state change, no secret exposure, and provider-friendly pacing. It
must not accept a browser URL or become an HTTP proxy (SSRF). Use bounded
concurrency, per-provider cooldown, cached results, TTL, and `next_eligible`
rather than probing on page refresh.

## Future backend boundary

## IH-2 backend adapter

`control_center.integration_health_adapter.WorkbenchIntegrationAdapter` is the
authoritative adapter. It accepts either `WORKBENCH_PLUGIN_REGISTRY_PATH`
(compiled registry JSON) or `WORKBENCH_PLUGINS_DIR` (the authoritative
`plugins/*/plugin.json` source). At least one must be explicitly configured;
there is no developer-machine path fallback. The adapter reads only the
allowlisted manifest fields and, when a plugins directory is supplied, bounded
Python source text to classify provider health capability. It never imports
plugins or returns arbitrary manifest content.

The inclusion filter remains exactly `search` and `reference_db`; action-capable
external `integration` plugins remain excluded. IDs come from the validated
Workbench slug and duplicate IDs fail safely rather than overwrite. Current
real-registry compatibility is 67 included, 49 explicit readiness signals, 10
plugin-liveness-only, and 8 no-safe-signal.

Optional `INTEGRATION_HEALTH_CONFIGURATION_PATH` may provide a JSON mapping
with only `auth_requirement`, `configuration_status`, and boolean
`credential_configured`. Optional
`INTEGRATION_HEALTH_READINESS_CACHE_PATH` is read-only and accepts only
provider status, checked timestamp, normalized failure reason, version, and a
short description. Missing or malformed optional sources degrade their
`data_sources` entry and do not make the report fail globally. IH-2 provides no
cache writer.

## IH-2 protected API

`GET /integration-health` is registered in the Control Center and mounted with
the existing `platform.manage_infra` dependency, matching Deployment Health
and Regression Health. It is read-only and no mutation methods are registered.
Authoritative registry failure returns HTTP 503 with only
`STATUS_UNAVAILABLE` and a safe generic message. One provider/cache/regression
failure leaves the rest of the report available.

The response is assembled from registry metadata, optional configuration,
optional cached readiness, and Regression Health source availability. No live
provider request occurs during GET. With no cache, provider status is
`NOT_CHECKED` and readiness remains `UNKNOWN` unless configuration state
deterministically produces another result.

The response includes `plugin_status` separately from provider status and
`health_signal_capability` as `READY_SIGNAL_EXISTS`, `PLUGIN_LIVENESS_ONLY`, or
`NO_SAFE_READINESS_SIGNAL`. Regression Health is source availability only; no
integration-level certification is inferred from the representative JASPAR
certification.

## IH-3 and IH-4 boundaries

IH-3 owns provider probe execution, static endpoint allowlists, bounded
timeouts/concurrency, rate-limit handling, cache writes, cooldown, and stale
result policy. It must not turn this GET route into a fan-out operation.

IH-4 owns the frontend API client/page/navigation work. IH-2 intentionally
does not modify frontend files, nginx, Compose, or navigation.

## IH-3 P0 probe service

`control_center.integration_health_probes` owns the internal bounded probe
runner and the normalized JSON cache writer. It is not imported by the GET
route and has no public trigger. The static allowlist currently enables these
small public/read-only GET checks:

| Integration | Probe | Success contract | Timeout/cooldown |
|---|---|---|---|
| ncbi | E-utilities `einfo` gene metadata | JSON header object | 5s / 300s |
| pubchem | CID 2244 molecular property | `PropertyTable` object | 5s / 300s |
| ensembl | REST ping | `ping` field | 5s / 300s |
| clinvar | E-utilities `einfo` ClinVar metadata | JSON header object | 5s / 300s |
| uniprot | TP53 entry metadata | `primaryAccession` | 5s / 300s |
| reactome | database version | non-empty version text | 5s / 300s |
| rcsb_pdb | 4HHB entry metadata | `rcsb_id` | 5s / 300s |

gnomAD, Open Targets, and STRING remain `UNKNOWN`/unsupported for IH-3:
their existing health methods use GraphQL or POST/version semantics and no
approved bounded GET contract was found. This is an intentional safety gap,
not a failed probe.

The runner uses at most four workers, one request per provider per run, no
automatic broad retries, no redirects, a 64 KiB response limit, and normalized
status/error mapping. It honors `Retry-After` by persisting
`next_eligible_at`; ordinary cooldown and display freshness are separate.
Failures are isolated per provider and written independently.

`JsonProbeCache` persists only normalized status, timestamps, failure class,
version, and safe short descriptions using an atomic replace. It never stores
credentials, tokens, headers, or raw payloads. IH-2 automatically reads this
cache through its existing read adapter. A cache hit during cooldown prevents
a provider request; stale results remain displayable with `STALE` freshness.

IH-3 unit tests use mocked transports only. IH-3.1 then performed one bounded
live request per approved provider on 2026-08-30, at
`2026-08-30T20:26:49Z` (UTC). The normalized results were: `ncbi`, `pubchem`,
`clinvar`, `reactome`, and `rcsb_pdb` `AVAILABLE`/`READY`; `ensembl`
`UNAVAILABLE`/`NOT_READY` with `TIMEOUT`; and `uniprot` `UNAVAILABLE`/
`NOT_READY` with `INVALID_RESPONSE`. These are point-in-time observations,
not permanent provider availability claims, and no raw response was retained.

The normalized cache contained seven provider-specific entries with only
allowlisted status, timestamps, failure class, version, and short description
fields. A second runner invocation immediately afterward made zero provider
calls because all seven entries were within the 300-second cooldown. The
IH-2 assembler consumed the cache without invoking the runner: its report
showed five ready, two not-ready, and the remaining 60 integrations unknown.
The GET route has no probe-runner dependency and therefore does not fan out to
providers. No 429, 401, or 403 occurred during this validation.

The implemented IH-2 contract is `GET /integration-health`, protected by the
existing `platform.manage_infra` permission used for Deployment Health and
Regression Health. It should return:

```json
{
  "schema_version": "1.0",
  "generated_at": "...",
  "summary": {"total": 0, "ready": 0, "degraded": 0, "not_ready": 0, "disabled": 0, "unknown": 0},
  "integrations": [],
  "data_sources": {"plugin_registry": "AVAILABLE", "configuration": "UNKNOWN", "provider_probes": "UNKNOWN", "regression_health": "AVAILABLE"},
  "warnings": []
}
```

One endpoint is sufficient for V1; add a detail route only if the payload
proves too large. The inventory must fail globally only when the authoritative
registry cannot be built. Configuration/probe/regression sources degrade
independently, and one provider failure never removes its peers.

## Counts, P0, and upstream gaps

Actual source counts: 67 biological/data integrations; 67 enabled; 0
disabled; 7 public search manifests plus 60 rich reference-db manifests;
health/readiness signal exists for 49; 10 need a small read-only probe review;
8 have no safe readiness signal. Configuration is not uniformly inspectable
without reading secrets, so configured/not-configured counts are intentionally
`UNKNOWN` in this discovery report. The same applies to current provider
availability for the 60 non-P0 integrations; IH-3.1 has evidence only for the
seven approved P0 probes documented above.

P0 should begin with NCBI, PubChem, Ensembl, gnomAD, ClinVar, UniProt,
Reactome, Open Targets, RCSB PDB, and STRING because their source has explicit
health clients, strong usage breadth, and existing opt-in live health tests.
This is a probe-priority recommendation, not a current-health ranking.

Required upstream V1 contract gaps are a stable provider-health result shape
and safe credential-presence metadata. P1 gaps are a small provider metadata
probe for the ten liveness-only clients and explicit release/version mapping.
Future gaps are object-download readiness and integration-level regression
certification mapping. A future manifest extension (`provider`, normalized
`integration_type`, static `health_probe`, `auth_requirement`,
`rate_limit_policy`, `external_api_version`) would reduce hardcoded mappings,
but `plugin.json` is not changed here.

## Security/privacy and implementation result

Serialization uses an explicit allowlist and redacts token-like text and
absolute paths. It never includes raw provider responses, credentials,
Authorization headers, cookies, private keys, or internal URLs. The model has
no HTTP/database/Docker/network dependency and is deterministic for explicit
inputs. It is not an implementation of the future route and has no
remediation controls.

The model tests cover public/authenticated/configuration states, disabled and
unimplemented records, available/degraded/rate-limited/unavailable/unknown
providers, stale evidence, evidence types, summaries, invalid metadata, and
redaction. Static validation is recorded in the Track D handoff; no
internet-dependent tests are part of this change.

## IH-4 Admin Console UI

The Admin Console now exposes Integration Health under Operations →
Infrastructure, alongside Regression Health and Deployment Health. The human
route is `/integration-health`; the browser data route is the distinct
`/integration-health/data`, which nginx rewrites to the protected backend
`GET /integration-health`. The same `platform.manage_infra` visibility gate is
used as the neighboring operational pages, while backend authorization remains
authoritative.

`IntegrationHealthPage` consumes the typed cached report through one GET API
client call. It renders backend-owned summary counts, provider status,
readiness, configuration/authentication metadata, freshness, normalized failure
classes, health-signal capability, safe evidence, and expandable details. It
keeps plugin liveness, provider availability, readiness, and certification as
separate dimensions. Filters are client-side only. There are no probe,
credential, enable/disable, retry, endpoint, or mutation controls; page
refresh cannot trigger provider probes or accept arbitrary URLs.

Unsupported providers such as gnomAD, Open Targets, and STRING remain visibly
`NOT_CHECKED`/`UNKNOWN` with their backend signal capability, not failed. The
IH-5/IH-5.1 certification covered deployed live behavior, stale/source
failure/recovery checks, and DOM-level no-fan-out verification; these
observations are recorded below and are not permanent provider guarantees.

## IH-5.1 live certification closure

On 2026-08-30, certification used the supported Auth login lifecycle. A
privileged identity received `200` for the protected data API, a recognized
authenticated non-privileged identity received `403`, and anonymous access
received `401`. The disposable non-privileged identity was suspended through
the supported platform lifecycle after validation; no credentials or tokens
were recorded.

Authenticated Chromium validation confirmed the `/integration-health` SPA
deep link, dynamic summary and table, client-side filters, expandable evidence
details, distinct provider/readiness columns, read-only controls, and honest
unsupported-provider states. A fresh page load and browser interactions
produced zero provider-origin requests; the browser used only the cached
Control Center report route. The existing `/integrations` API/page surface
remained separate.

Temporary normalized fixtures verified that stale evidence remains visible as
`STALE` with its original timestamp; a `TIMEOUT` result renders as
`UNAVAILABLE`/`NOT_READY`; and `DEGRADED`/`RATE_LIMIT` remains visible without
retry or cooldown bypass. The readiness-cache source and Regression Health
source were each made unavailable independently while the report remained
available and unknown evidence stayed unknown. A missing authoritative
registry returned the safe generic `503` response and the SPA error state.
All fixtures were removed and normal sources recovered. These are validation
observations, not permanent provider availability guarantees.

The readiness semantic regression is covered explicitly: known provider
evidence takes precedence over unknown configuration metadata, while
configuration remains independently unknown. The optional Regression Health
source now reports `UNAVAILABLE` when its artifact cannot be loaded. No
provider probes are triggered by GET, page refresh, filtering, searching, or
detail expansion. API methods remain read-only, static provider destinations
remain backend-owned, and live responses contain no secrets, raw payloads,
private paths, or stack traces.
