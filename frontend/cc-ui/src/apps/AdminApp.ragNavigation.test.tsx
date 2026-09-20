import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import AdminApp from './AdminApp'
import * as auth from '../auth'
import type { SessionUser } from '../auth'

// Regression coverage for the Admin Console nav bug: an already-
// authenticated admin clicking the Knowledge > RAG or Knowledge > PubMed
// sidebar entries was bounced straight back to the "OmniBioAI Admin
// Portal" login screen instead of landing on the RAG/PubMed page.
//
// Root cause: rag.ts's apiFetch() called reportUnauthorized() on ANY 401,
// but a 401 relayed from omnibioai-rag (the proxy forwards the admin's own
// token and RAG verifies/authorizes it itself) says nothing about the
// admin's own control-center session. reportUnauthorized() cleared the
// admin's perfectly valid token and fired UNAUTHORIZED_EVENT, which
// AuthGate treats identically to a real session expiry.
//
// The fix keys off structured data: routes_rag_proxy.py tags every
// response it relays from RAG with X-Upstream-Service: rag, and rag.ts
// only ends the session for a 401 that lacks that tag (i.e. one
// control-center itself produced). The stubs below therefore model both
// origins with REALISTIC bodies -- including the exact error wording RAG
// really returns -- because the behavior under test must not depend on
// wording (an earlier version of this file used bodies with no `detail`,
// which hid a real-world mismatch).
//
// Unlike AdminApp.test.tsx, RAGPage is deliberately NOT mocked here --
// the behavior lives in the real SidebarNav -> AdminApp -> RAGPage ->
// rag.ts -> fetch chain, which a mocked RAGPage would hide. DashboardPage
// (the default landing page, rendered before the RAG/PubMed click) is
// mocked purely to avoid its own unrelated real GET /dashboard/summary
// call racing the /rag/* fetches this file stubs below.

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
    ensureSession: vi.fn(),
    getSessionUser: vi.fn(),
    hasAdminAccess: vi.fn(),
    hasPermission: vi.fn(),
    hasOrganizationsAccess: vi.fn(),
    hasPlatformAdminAccess: vi.fn(),
  }
})

vi.mock('../api', () => ({
  fetchSummary: vi.fn().mockResolvedValue({ overall_status: 'UP', services: [] }),
  fetchReportStatus: vi.fn().mockResolvedValue({ report_exists: false, status: 'idle' }),
  triggerGenerate: vi.fn(),
}))

vi.mock('../pages/DashboardPage', () => ({ default: () => <div data-testid="DashboardPage" /> }))

const admin: SessionUser = {
  userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
  permissions: ['manage_config'], orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
}

function clickNav(label: string) {
  fireEvent.click(screen.getByText(label))
}

type Origin = 'rag' | 'control-center'

/** Stubs global fetch so every /rag/* call resolves with `status` and a
 * realistic `{detail}` body, tagged the way routes_rag_proxy.py tags
 * responses relayed from RAG (origin 'rag') or left untagged the way its
 * own control-center-generated responses are (origin 'control-center').
 * Fails the test loudly on any other URL. */
function stubRagFetch(status: number, origin: Origin, detail: string) {
  const headers: Record<string, string> = origin === 'rag' ? { 'X-Upstream-Service': 'rag' } : {}
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/rag/')) {
      return Promise.resolve(new Response(JSON.stringify({ detail }), { status, headers }))
    }
    return Promise.reject(new Error(`unexpected fetch in AdminApp RAG navigation test: ${url}`))
  }))
}

const RAG_REJECTED_TOKEN = 'Invalid, expired, or revoked token'

describe('AdminApp: RAG/PubMed sidebar navigation', () => {
  beforeEach(() => {
    window.history.pushState(null, '', '/')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('as an authenticated admin', () => {
    beforeEach(() => {
      vi.mocked(auth.getToken).mockReset().mockReturnValue('token-456')
      vi.mocked(auth.ensureSession).mockReset().mockResolvedValue(admin)
      vi.mocked(auth.getSessionUser).mockReset().mockReturnValue(admin)
      vi.mocked(auth.hasAdminAccess).mockReset().mockReturnValue(true)
      vi.mocked(auth.hasPermission).mockReset().mockReturnValue(true)
      vi.mocked(auth.hasOrganizationsAccess).mockReset().mockReturnValue(true)
      vi.mocked(auth.hasPlatformAdminAccess).mockReset().mockReturnValue(true)
    })

    it('navigates to RAG without redirecting to the login screen when RAG itself rejects the token (401)', async () => {
      stubRagFetch(401, 'rag', RAG_REJECTED_TOKEN)
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      expect(await screen.findByText('RAG did not accept your session')).toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
      expect(screen.queryByText('Your account does not have permission to access the Admin Portal.')).not.toBeInTheDocument()
    })

    it('navigates to PubMed without redirecting to the login screen when RAG itself rejects the token (401)', async () => {
      stubRagFetch(401, 'rag', RAG_REJECTED_TOKEN)
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('PubMed')

      expect(await screen.findByText('RAG did not accept your session')).toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
    })

    it('shows an insufficient-permissions state (not a credential error) and stays signed in on a RAG 403', async () => {
      stubRagFetch(403, 'rag', 'Insufficient permissions')
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      expect(await screen.findByText('Insufficient permissions')).toBeInTheDocument()
      expect(screen.queryByText(/service credential/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
    })

    it('does not depend on error wording: an unfamiliar RAG 401 message is handled the same way', async () => {
      stubRagFetch(401, 'rag', 'some message the backend may reword tomorrow')
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      expect(await screen.findByText('RAG did not accept your session')).toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
    })

    it('still drops to the login screen when control-center itself reports the admin session invalid (401 with no upstream tag)', async () => {
      stubRagFetch(401, 'control-center', 'Invalid or expired token')
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
    })

    it('still renders real RAG data on success (sidebar destination is correct, not just error-tolerant)', async () => {
      vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/rag/studies')) {
          return Promise.resolve(new Response(JSON.stringify({ studies: [{ name: 'covid19', abstract_count: 5 }] }), { status: 200 }))
        }
        if (url.includes('/rag/cache-stats') || url.includes('/rag/health')) {
          return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      expect(await screen.findByText('covid19')).toBeInTheDocument()
    })

    it('does not offer RAG/PubMed to an admin session without hasAdminAccess (authorization unchanged)', async () => {
      vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
      vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
      stubRagFetch(401, 'rag', RAG_REJECTED_TOKEN)
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      expect(screen.queryByText('RAG')).not.toBeInTheDocument()
      expect(screen.queryByText('PubMed')).not.toBeInTheDocument()
    })
  })

  describe('without an authenticated session', () => {
    it('an unauthenticated visitor still lands on the login screen, not RAGPage (no token at all)', async () => {
      vi.mocked(auth.getToken).mockReset().mockReturnValue(null)
      render(<AdminApp />)
      expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
      expect(screen.queryByText('RAG')).not.toBeInTheDocument()
      expect(screen.queryByText('PubMed')).not.toBeInTheDocument()
    })
  })
})
