import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import PublicHealthPage from './PublicHealthPage'

vi.mock('../api', () => ({
  fetchHealth: vi.fn(),
}))

describe('PublicHealthPage', () => {
  beforeEach(async () => {
    vi.mocked((await import('../api')).fetchHealth).mockReset()
  })

  it('shows Operational when GET /health returns {"status":"ok"}', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchHealth).mockResolvedValue({ status: 'ok' })
    render(<PublicHealthPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Operational')).toBeInTheDocument())
  })

  it('shows Unreachable when the request fails', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchHealth).mockRejectedValue(new Error('/health 503'))
    render(<PublicHealthPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Unreachable')).toBeInTheDocument())
  })

  it('never renders a hostname, LAN IP, container name, or mount path', async () => {
    // Contract check: this page only ever calls GET /health, whose own
    // response shape is exactly {"status": "ok"} (routes_health.py) --
    // there is no field this component could render that carries
    // internal topology, unlike HealthPage.tsx's /summary-sourced
    // ServiceResult.target.
    const api = await import('../api')
    vi.mocked(api.fetchHealth).mockResolvedValue({ status: 'ok' })
    render(<PublicHealthPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Operational')).toBeInTheDocument())
    expect(screen.queryByText(/:\/\//)).not.toBeInTheDocument()
    expect(screen.queryByText(/localhost|127\.0\.0\.1|redis:|mysql:/)).not.toBeInTheDocument()
  })

  it('re-fetches when refreshKey changes', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchHealth).mockResolvedValue({ status: 'ok' })
    const { rerender } = render(<PublicHealthPage refreshKey={0} />)
    await waitFor(() => expect(api.fetchHealth).toHaveBeenCalledTimes(1))
    rerender(<PublicHealthPage refreshKey={1} />)
    await waitFor(() => expect(api.fetchHealth).toHaveBeenCalledTimes(2))
  })
})
