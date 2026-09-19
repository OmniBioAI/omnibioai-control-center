import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import RAGPage from './RAGPage'
import * as rag from '../../rag'
import type { StudiesResult, CacheStats, RagHealth } from '../../rag'

vi.mock('../../rag', async () => {
  const actual = await vi.importActual<typeof import('../../rag')>('../../rag')
  return { ...actual, fetchStudies: vi.fn(), fetchCacheStats: vi.fn(), fetchRagHealth: vi.fn() }
})

const studies: StudiesResult = {
  studies: [
    { name: 'covid19', abstract_count: 1204 },
    { name: 'oncology', abstract_count: 831 },
  ],
}

const health: RagHealth = {
  status: 'ok', version: '1.1.0', faiss_version: '1.8.0',
  cache: { enabled: true, connected: true, cached_queries: 42, hit_rate: 80 },
}
const cacheStats: CacheStats = { enabled: true, connected: true, cached_queries: 42, ttl_seconds: 3600, hits: 120, misses: 30, hit_rate: 80 }

describe('RAGPage', () => {
  beforeEach(() => {
    vi.mocked(rag.fetchStudies).mockReset()
    vi.mocked(rag.fetchRagHealth).mockReset().mockResolvedValue(health)
    vi.mocked(rag.fetchCacheStats).mockReset().mockResolvedValue(cacheStats)
  })

  it('shows a loading state while the knowledge base is in flight', async () => {
    vi.mocked(rag.fetchStudies).mockReturnValue(new Promise(() => {}))
    render(<RAGPage />)
    expect(await screen.findByText('Loading knowledge base…')).toBeInTheDocument()
  })

  it('shows the empty state when no collections are indexed yet', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue({ studies: [] })
    render(<RAGPage />)
    expect(await screen.findByText('No indexed collections yet.')).toBeInTheDocument()
  })

  it('renders the Knowledge Base tab with real study data', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue(studies)
    render(<RAGPage />)

    expect(await screen.findByRole('columnheader', { name: 'Collection' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Abstracts Indexed' })).toBeInTheDocument()
    expect(screen.getByText('covid19')).toBeInTheDocument()
    expect(screen.getByText('1,204')).toBeInTheDocument()
  })

  it('shows the RAG service credential state when the backend 403s', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new Error('/rag/studies 403'))
    render(<RAGPage />)
    expect(await screen.findByText('RAG service credential unavailable')).toBeInTheDocument()
    expect(screen.queryByText('No indexed collections yet.')).not.toBeInTheDocument()
  })

  // Regression test for the Admin Console nav bug: an authenticated
  // admin clicking RAG/PubMed was bounced straight to the login screen
  // whenever routes_rag_proxy.py relayed a 401 from omnibioai-rag's own
  // RAGBIO_API_KEY service-credential check -- rag.ts's apiFetch used to
  // treat ANY 401 as evidence the *admin's own* session was invalid and
  // force-logged them out before this "denied" state ever had a chance
  // to render (see rag.ts's own comment on why it no longer does that).
  // This test proves the classify()/ServiceCredentialState path handles
  // a 401 exactly like a 403 -- a service-credential problem, not a
  // reason to leave this page at all.
  it('shows the RAG service credential state when the backend 401s, not a forced logout', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new Error('/rag/studies 401'))
    render(<RAGPage />)
    expect(await screen.findByText('RAG service credential unavailable')).toBeInTheDocument()
    expect(screen.queryByText('No indexed collections yet.')).not.toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValueOnce(new Error('/rag/studies 503'))
    vi.mocked(rag.fetchStudies).mockResolvedValueOnce(studies)
    const user = userEvent.setup()
    render(<RAGPage />)

    expect(await screen.findByText('/rag/studies 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByText('covid19')).toBeInTheDocument())
  })

  it('switches to the PubMed / Literature Index tab and shows aggregated totals', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue(studies)
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('covid19')

    await user.click(screen.getByRole('button', { name: 'PubMed / Literature Index' }))

    expect(await screen.findByText('Collections')).toBeInTheDocument()
    expect(screen.getByText('Total Abstracts Indexed')).toBeInTheDocument()
    // 1204 + 831 = 2035, real sum of the mocked fixture, not invented.
    expect(screen.getByText('2,035')).toBeInTheDocument()
  })

  it('switches to the Query Service Status tab and shows health + cache stats', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue({ studies: [] })
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('No indexed collections yet.')

    await user.click(screen.getByRole('button', { name: 'Query Service Status' }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText('1.1.0')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
  })

  it('shows health even when cache-stats independently fails', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue({ studies: [] })
    vi.mocked(rag.fetchCacheStats).mockRejectedValue(new Error('/rag/cache-stats 503'))
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('No indexed collections yet.')

    await user.click(screen.getByRole('button', { name: 'Query Service Status' }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText(/cache-stats endpoint didn't respond/)).toBeInTheDocument()
  })
})
