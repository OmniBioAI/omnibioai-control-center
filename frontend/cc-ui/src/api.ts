import { authHeaders, reportUnauthorized } from './auth'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// Wraps fetch() with the admin Authorization header and centralizes the
// 401 handling (main.py's require_admin gate) so every call site doesn't
// have to re-implement "session expired, go back to login".
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

export interface ServiceResult {
  name: string
  type: string
  target: string
  status: 'UP' | 'WARN' | 'DOWN'
  latency_ms: number | null
  message: string
  ui_url?: string | null
}

export interface DiskResult {
  name: string
  type: string
  target: string
  status: 'UP' | 'WARN' | 'DOWN'
  latency_ms: number | null
  message: string
}

export interface SummaryResponse {
  overall_status: 'UP' | 'WARN' | 'DOWN'
  generated_at: string
  services: ServiceResult[]
  system: { disk: DiskResult[] }
}

export interface ReportStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  started_at: string | null
  finished_at: string | null
  message: string
  report_exists: boolean
  report_generated_at: string | null
}

export interface Container {
  Names: string
  Image: string
  Status: string
  State?: string
  RunningFor: string
  Ports: string
  Command?: string
  CreatedAt?: string
}

export interface ContainersResponse {
  containers: Container[]
  running: number
  stopped: number
  error?: string
}

export interface SifImage {
  tool: string
  category: string
  sif_path: string | null
  exists: boolean
  size_mb: number
}

export interface SifImagesResponse {
  images: SifImage[]
  built: number
  missing: number
  total_gb: number
}

export interface PluginImage {
  plugin: string
  name: string
  category: string
  image: string
  local_status: 'present' | 'missing' | 'unknown'
  size_mb: number
}

export interface PluginImagesResponse {
  plugins: PluginImage[]
  present: number
  missing: number
}

export async function fetchSummary(): Promise<SummaryResponse> {
  const r = await apiFetch(`${BASE}/summary`)
  if (!r.ok) throw new Error(`/summary ${r.status}`)
  return r.json()
}

export async function fetchConfig(): Promise<string> {
  const r = await apiFetch(`${BASE}/config`)
  if (!r.ok) throw new Error(`/config ${r.status}`)
  return r.text()
}

export interface ProjectRow {
  name: string; full: string; cat: string; catLabel: string
  files: number; code: number; comment: number; blank: number; pct: number
}

export interface LanguageRow {
  name: string; type: string; typeLabel: string
  files: number; code: number; comment: number; blank: number; pct: number
}

export interface CoverageRow {
  repo: string; status: string; pct: number | null
  stmts: number | null; missed: number | null; branches: number | null; failUnder: number | null
}

export interface ReportData {
  generated_at: string
  grand: { files: number; code: number; comment: number; blank: number }
  projects: ProjectRow[]
  languages: LanguageRow[]
  coverage: CoverageRow[]
}

export async function fetchReportData(): Promise<ReportData> {
  const r = await apiFetch(`${BASE}/report/data`)
  if (!r.ok) throw new Error(`/report/data ${r.status}`)
  return r.json()
}

export async function fetchReportStatus(): Promise<ReportStatus> {
  const r = await apiFetch(`${BASE}/report/status`)
  if (!r.ok) throw new Error(`/report/status ${r.status}`)
  return r.json()
}

export async function triggerGenerate(): Promise<void> {
  const r = await apiFetch(`${BASE}/report/generate`, { method: 'POST' })
  if (!r.ok && r.status !== 409) throw new Error(`/report/generate ${r.status}`)
}

export async function addService(name: string, type: string, url: string): Promise<void> {
  const r = await apiFetch(`${BASE}/config/service`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, type, url }),
  })
  if (!r.ok) throw new Error(`/config/service ${r.status}`)
}

export async function fetchContainers(): Promise<ContainersResponse> {
  const r = await apiFetch(`${BASE}/docker/containers`)
  if (!r.ok) throw new Error(`/docker/containers ${r.status}`)
  return r.json()
}

export async function fetchSifImages(): Promise<SifImagesResponse> {
  const r = await apiFetch(`${BASE}/docker/sif-images`)
  if (!r.ok) throw new Error(`/docker/sif-images ${r.status}`)
  return r.json()
}

export async function fetchPluginImages(): Promise<PluginImagesResponse> {
  const r = await apiFetch(`${BASE}/docker/plugin-images`)
  if (!r.ok) throw new Error(`/docker/plugin-images ${r.status}`)
  return r.json()
}
