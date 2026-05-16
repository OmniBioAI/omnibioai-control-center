const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

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
  const r = await fetch(`${BASE}/summary`)
  if (!r.ok) throw new Error(`/summary ${r.status}`)
  return r.json()
}

export async function fetchConfig(): Promise<string> {
  const r = await fetch(`${BASE}/config`)
  if (!r.ok) throw new Error(`/config ${r.status}`)
  return r.text()
}

export async function fetchReportStatus(): Promise<ReportStatus> {
  const r = await fetch(`${BASE}/report/status`)
  if (!r.ok) throw new Error(`/report/status ${r.status}`)
  return r.json()
}

export async function triggerGenerate(): Promise<void> {
  const r = await fetch(`${BASE}/report/generate`, { method: 'POST' })
  if (!r.ok && r.status !== 409) throw new Error(`/report/generate ${r.status}`)
}

export async function addService(name: string, type: string, url: string): Promise<void> {
  const r = await fetch(`${BASE}/config/service`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, type, url }),
  })
  if (!r.ok) throw new Error(`/config/service ${r.status}`)
}

export async function fetchContainers(): Promise<ContainersResponse> {
  const r = await fetch(`${BASE}/docker/containers`)
  if (!r.ok) throw new Error(`/docker/containers ${r.status}`)
  return r.json()
}

export async function fetchSifImages(): Promise<SifImagesResponse> {
  const r = await fetch(`${BASE}/docker/sif-images`)
  if (!r.ok) throw new Error(`/docker/sif-images ${r.status}`)
  return r.json()
}

export async function fetchPluginImages(): Promise<PluginImagesResponse> {
  const r = await fetch(`${BASE}/docker/plugin-images`)
  if (!r.ok) throw new Error(`/docker/plugin-images ${r.status}`)
  return r.json()
}
