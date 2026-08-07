import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DashboardPage from './DashboardPage'
import * as dashboard from '../dashboard'

vi.mock('../dashboard', async () => {
  const actual = await vi.importActual<typeof import('../dashboard')>('../dashboard')
  return { ...actual, fetchDashboardSummary: vi.fn() }
})

const FULL_SUMMARY: dashboard.DashboardSummary = {
  generated_at: '2026-08-04T10:00:00Z',
  identity: { organizations: 18, users: 246, teams: 12, roles: 6, active_sessions: null },
  ai_platform: { registered_models: 118, active_models: 42, embedding_models: null, llm_providers: 3 },
  knowledge: { rag_collections: 23, indexed_documents: 4820, indexed_publications: 4820, knowledge_bases: 23 },
  workflow: { workflow_bundles: 31, running_jobs: 5, queued_jobs: 4, failed_jobs: 1 },
  infrastructure: {
    containers_running: 17, containers_stopped: 1, services_healthy: 17, services_total: 18,
    gpu_utilization_pct: 68, storage_used_bytes: 2_400_000_000_000, storage_total_bytes: 4_000_000_000_000,
    cpu_pct: null, memory_pct: null,
  },
  operations: { health: 'UP', alerts: 1, active_services: 17, uptime: null },
  business: {
    organization_id: 7, organization_name: 'Acme Corp', plan_name: 'Enterprise',
    subscription_status: 'active', usage_services_count: 3, billing_service_available: true,
  },
}

const BUSINESS_UNAVAILABLE_SUMMARY: dashboard.DashboardSummary = {
  ...FULL_SUMMARY,
  business: {
    organization_id: 7, organization_name: 'Acme Corp', plan_name: null,
    subscription_status: null, usage_services_count: null, billing_service_available: false,
  },
}

const BUSINESS_EMPTY_SUMMARY: dashboard.DashboardSummary = {
  ...FULL_SUMMARY,
  business: {
    organization_id: null, organization_name: null, plan_name: null,
    subscription_status: null, usage_services_count: null, billing_service_available: null,
  },
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.mocked(dashboard.fetchDashboardSummary).mockReset()
  })

  it('renders live numbers from GET /dashboard/summary across every section', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(FULL_SUMMARY)
    render(<DashboardPage />)

    expect(await screen.findByText('18')).toBeInTheDocument()   // Organizations
    expect(screen.getByText('246')).toBeInTheDocument()          // Users
    expect(screen.getByText('118')).toBeInTheDocument()          // Registered Models
    expect(screen.getAllByText('23')).toHaveLength(2)            // RAG Collections + Knowledge Bases (same figure, documented)
    expect(screen.getByText('31')).toBeInTheDocument()           // Workflow Bundles
    expect(screen.getByText('17/18')).toBeInTheDocument()        // Services
    expect(screen.getByText('Healthy')).toBeInTheDocument()      // Operations > Health
    expect(screen.getByText('2.4 TB')).toBeInTheDocument()       // Storage
    expect(screen.getByText('Enterprise')).toBeInTheDocument()   // Business > Plan
    expect(screen.getByText('active')).toBeInTheDocument()       // Business > Subscription
    expect(screen.getByText('Available')).toBeInTheDocument()    // Business > Billing Service
  })

  it('renders "--" for every field the backend returned null for, never a fabricated number', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(FULL_SUMMARY)
    render(<DashboardPage />)
    await screen.findByText('18')

    // Active Sessions, Embedding Models, CPU, Memory, Uptime are null in
    // FULL_SUMMARY -- each renders as an em dash. Business is fully
    // populated in this fixture (PR C: no longer structurally
    // placeholder), so it contributes none here.
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(5)
  })

  it('shows every section heading', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(FULL_SUMMARY)
    render(<DashboardPage />)
    await screen.findByText('18')

    for (const heading of ['Identity', 'AI Platform', 'Knowledge Platform', 'Workflow Platform', 'Infrastructure', 'Operations', 'Business']) {
      expect(screen.getByText(heading)).toBeInTheDocument()
    }
  })

  it('degrades to placeholders everywhere without throwing when the fetch fails entirely', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockRejectedValue(new Error('network error'))
    render(<DashboardPage />)

    expect(await screen.findByText(/Couldn't load the platform summary/)).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(10)
  })

  it('flags only the structurally-unavailable fields as preview data -- Business is no longer one of them', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(FULL_SUMMARY)
    render(<DashboardPage />)
    await screen.findByText('18')

    // PR C: Business now has a real live source (routes_dashboard.py's
    // _business_section()) -- it must never carry the "Preview data" tag
    // again, unlike Active Sessions/Embedding Models/CPU/Memory/Uptime,
    // which still have no live source anywhere in this backend.
    const previewTags = screen.getAllByText('Preview data')
    expect(previewTags.length).toBe(5)
  })

  // ── Business widget (PR C) ───────────────────────────────────────────

  it('shows the empty state (no organization membership) as "--"/"Unknown", not fabricated values', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(BUSINESS_EMPTY_SUMMARY)
    render(<DashboardPage />)
    await screen.findByText('18')

    // Plan and Usage are MetricCards (null -> em dash); Subscription and
    // Billing Service are StatusCards (null -> "Unknown"), not fabricated
    // as "Active" or similar.
    expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(2)
  })

  it('shows the billing service as Unavailable, distinct from a plain empty state', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockResolvedValue(BUSINESS_UNAVAILABLE_SUMMARY)
    render(<DashboardPage />)
    await screen.findByText('18')

    expect(await screen.findByText('Unavailable')).toBeInTheDocument()
  })

  it('degrades the Business widget without throwing when the whole fetch fails', async () => {
    vi.mocked(dashboard.fetchDashboardSummary).mockRejectedValue(new Error('network error'))
    render(<DashboardPage />)

    expect(await screen.findByText(/Couldn't load the platform summary/)).toBeInTheDocument()
    expect(screen.getByText('Business')).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(2)
  })
})
