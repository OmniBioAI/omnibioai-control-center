import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import RAGPage from './RAGPage'
import * as rag from '../../rag'
import { RagRequestError } from '../../rag'
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

  // Classification is driven by the structured HTTP status on RagRequestError,
  // never by message text: each case below uses wording that would fool a
  // string matcher in one direction or the other.
  it('shows an insufficient-permissions state for a 403, not a service-credential error', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new RagRequestError('Insufficient permissions', 403))
    render(<RAGPage />)
    expect(await screen.findByText('Insufficient permissions')).toBeInTheDocument()
    expect(screen.getByText(/dataset\.read/)).toBeInTheDocument()
    expect(screen.queryByText(/service credential/i)).not.toBeInTheDocument()
    expect(screen.queryByText('No indexed collections yet.')).not.toBeInTheDocument()
  })

  it('shows "RAG did not accept your session" for a 401 and says the console session is intact', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new RagRequestError('Invalid, expired, or revoked token', 401))
    render(<RAGPage />)
    expect(await screen.findByText('RAG did not accept your session')).toBeInTheDocument()
    expect(screen.getByText(/Admin Console session is still active/)).toBeInTheDocument()
    expect(screen.queryByText(/service credential/i)).not.toBeInTheDocument()
  })

  it('classifies by HTTP status, not message text: a 403 with unrelated wording is still permissions', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new RagRequestError('something entirely different', 403))
    render(<RAGPage />)
    expect(await screen.findByText('Insufficient permissions')).toBeInTheDocument()
  })

  it('does not infer permissions from message text: a plain Error ending in " 403" is a generic error', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new Error('/rag/studies 403'))
    render(<RAGPage />)
    expect(await screen.findByText('/rag/studies 403')).toBeInTheDocument()
    expect(screen.queryByText('Insufficient permissions')).not.toBeInTheDocument()
  })

  it('treats a RagRequestError with a non-auth status as a generic error with retry', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new RagRequestError('rag-service unreachable', 503))
    render(<RAGPage />)
    expect(await screen.findByText('rag-service unreachable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('shows the same permission state on the PubMed / Literature Index tab', async () => {
    vi.mocked(rag.fetchStudies).mockRejectedValue(new RagRequestError('nope', 403))
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('Insufficient permissions')

    await user.click(screen.getByRole('button', { name: 'PubMed / Literature Index' }))

    expect(await screen.findByText('Insufficient permissions')).toBeInTheDocument()
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

  it('explains a cache-stats 403 as a permission (manage_all_orgs) issue and keeps health visible', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue({ studies: [] })
    vi.mocked(rag.fetchCacheStats).mockRejectedValue(new RagRequestError('Insufficient permissions', 403))
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('No indexed collections yet.')

    await user.click(screen.getByRole('button', { name: 'Query Service Status' }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText(/manage_all_orgs/)).toBeInTheDocument()
    expect(screen.queryByText(/service credential/i)).not.toBeInTheDocument()
  })

  it('explains a cache-stats 401 without implying the console session ended', async () => {
    vi.mocked(rag.fetchStudies).mockResolvedValue({ studies: [] })
    vi.mocked(rag.fetchCacheStats).mockRejectedValue(new RagRequestError('Invalid, expired, or revoked token', 401))
    const user = userEvent.setup()
    render(<RAGPage />)
    await screen.findByText('No indexed collections yet.')

    await user.click(screen.getByRole('button', { name: 'Query Service Status' }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText(/Admin Console session is still active/)).toBeInTheDocument()
  })
})
