// Public Platform Overview (control.omnibioai.org): data for the anonymous
// showcase page. Every call here goes to a route that answers without a
// token and returns the anonymous-safe shape (core/public_view.py and each
// route's own public contract) -- no Authorization header is sent, same
// as the rest of the ControlApp build.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json() as Promise<T>
}

// ── Catalog snapshot ─────────────────────────────────────────────────────
// Headline counts from the documentation's generated catalogs
// (omnibioai-docs site/static/generated/catalog-summary.json). They are a
// dated snapshot, not live values, and describe what is registered or
// configured in source -- the page says so next to them.
export const CATALOG_SNAPSHOT = {
  asOf: '2026-09-19',
  docsUrl: 'https://docs.omnibioai.org/catalogs/',
  items: [
    { label: 'Workbench plugins', value: '501', href: 'https://docs.omnibioai.org/plugins/' },
    { label: 'Integrations', value: '66', href: 'https://docs.omnibioai.org/integrations/' },
    { label: 'Workflows', value: '1000+', href: 'https://docs.omnibioai.org/workflows-catalog/' },
    { label: 'TES tool definitions', value: '12,276', href: 'https://docs.omnibioai.org/tools/' },
    { label: 'Reference database plugins', value: '130', href: 'https://docs.omnibioai.org/reference-data/database-catalog/' },
    { label: 'API routes', value: '219', href: 'https://docs.omnibioai.org/api-reference/' },
  ],
} as const

// ── Live shapes ──────────────────────────────────────────────────────────

export interface PublicStats {
  generated_at: string | null
  total_lines: number | null
  total_files: number | null
  ecosystem_coverage_percent: number | null
  repos_measured: number
}

export interface UsageStatus {
  runs_by_day: { date: string; count: number }[]
  top_plugins: { name: string; runs_30d: number }[]
  workflow_success_rate_pct: number
  success_rate_caveat?: string
}

export interface PublicAiAndWorkflow {
  ai_platform: {
    registered_models: number | null
    active_models: number | null
    embedding_models: number | null
    llm_providers: number | null
  } | null
  workflow: { workflow_bundles: number | null } | null
}

export interface ReferenceStatus {
  available: boolean
  organisms: { organism: string; assembly: string; indexes: Record<string, boolean> }[]
}

export type BackendStatus = Record<string, { label: string; configured: boolean }>

export interface PublicIssue {
  id: string
  title: string
  severity: string
  status: string
  area: string | null
  opened_at: string | null
}

export const fetchPublicStats = () => getJson<PublicStats>('/report/public-stats')
export const fetchUsage = () => getJson<UsageStatus>('/usage')
export const fetchAiAndWorkflow = () => getJson<PublicAiAndWorkflow>('/dashboard/summary')
export const fetchReferenceStatus = () => getJson<ReferenceStatus>('/reference')
export const fetchBackends = () => getJson<BackendStatus>('/cloud')

export async function fetchOpenIssues(): Promise<PublicIssue[]> {
  const data = await getJson<{ issues: PublicIssue[] }>('/known-issues')
  // Title, severity, area and date only -- descriptions are written for
  // operators and are not shown on the public page.
  return (data.issues ?? [])
    .filter(i => i.status !== 'resolved')
    .map(({ id, title, severity, status, area, opened_at }) => ({ id, title, severity, status, area, opened_at }))
}

// ── Showcase (curated, schema-validated -- core/showcase.py) ─────────────

export interface Showcase {
  available: boolean
  as_of: string | null
  releases: { version: string; date: string | null; url: string | null }[]
  benchmarks: { pipeline: string; dataset: string; metrics: Record<string, number | string>; date: string; url: string | null }[]
  example_runs: { title: string; dataset: string; description: string; report_url: string | null; inputs_url: string | null }[]
  tool_versions: { name: string; version: string; category: string | null }[]
  publications: { year: number; title: string; venue: string; url: string | null }[]
  test_evidence: { suite: string; date: string; passed: number; failed: number; skipped: number; blocked: number; url: string | null }[]
  repo_coverage: { repo: string; coverage_pct: number; date: string }[]
  ci_repos: { repo: string; workflow: string; label: string | null }[]
  security_controls: { area: string; status: 'implemented' | 'partial' | 'planned'; summary: string }[]
  data_handling: string[]
  limitations: { title: string; detail: string; url: string | null }[]
  regression: {
    generated_at: string | null
    freshness: string | null
    phases: Record<string, { status: string; certification_status: string }>
    capabilities_total: number
    capabilities_by_certification: Record<string, number>
  } | null
}

export interface UptimeSummary {
  window_days: number
  sample_seconds: number
  services: { label: string; overall_pct: number | null; days: { date: string; availability_pct: number | null }[] }[]
}

export const fetchShowcase = () => getJson<Showcase>('/showcase')
export const fetchUptime = () => getJson<UptimeSummary>('/uptime')
