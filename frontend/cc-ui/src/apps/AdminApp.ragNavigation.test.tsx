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
// Root cause: rag.ts's apiFetch() called reportUnauthorized() on ANY 401
// response, but /rag/studies and /rag/cache-stats (routes_rag_proxy.py)
// authenticate upstream with a control-center-held RAGBIO_API_KEY
// service credential, not the viewing admin's own bearer token (see
// rag.ts's own module comment) -- a 401 there reflects that shared
// secret being missing/misconfigured/rejected by omnibioai-rag, not the
// admin's own control-center session. reportUnauthorized() cleared the
// admin's perfectly valid token and fired UNAUTHORIZED_EVENT, which
// AuthGate (this file's own auth-gate state machine) treats identically
// to a real session expiry: it drops straight back to LoginScreen. Every
// other sidebar destination's data layer either forwards the caller's
// own Authorization header upstream, or is checked entirely by
// control-center's own require_permission dependency -- for those, a
// 401 genuinely does mean the admin's session is invalid, so this bug is
// specific to RAG/PubMed's shared-service-credential model.
//
// Unlike AdminApp.test.tsx, RAGPage is deliberately NOT mocked here --
// this bug lives in the real SidebarNav -> AdminApp -> RAGPage -> rag.ts
// -> fetch chain, which a mocked RAGPage would hide. DashboardPage (the
// default landing page, rendered before the RAG/PubMed click) is mocked
// purely to avoid its own unrelated real GET /dashboard/summary call
// racing the /rag/* fetches this file stubs below.

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

/** Stubs global fetch so every /rag/* call resolves with `status`, and
 * fails the test loudly on any other URL (nothing else should be
 * called once we've navigated to RAG/PubMed with DashboardPage mocked).
 * Deliberately no `detail`/`error` field in the body -- rag.ts's own
 * _errorMessage() prefers those over its generic "<path> <status>"
 * message, and RAGPage's classify() keys off that generic message
 * ending in " 401"/" 403" to render the credential-denied state. */
function stubRagFetch(status: number, body: unknown = {}) {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/rag/')) {
      return Promise.resolve(new Response(JSON.stringify(body), { status }))
    }
    return Promise.reject(new Error(`unexpected fetch in AdminApp RAG navigation test: ${url}`))
  }))
}

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

    it('navigates to RAG without redirecting to the login screen, even when the RAG service credential 401s', async () => {
      stubRagFetch(401)
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('RAG')

      // The real RAGPage renders its own denied state -- not a bounce
      // back to LoginScreen.
      expect(await screen.findByText('RAG service credential unavailable')).toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
      expect(screen.queryByText('Your account does not have permission to access the Admin Portal.')).not.toBeInTheDocument()
    })

    it('navigates to PubMed without redirecting to the login screen, even when the RAG service credential 401s', async () => {
      stubRagFetch(401)
      render(<AdminApp />)
      await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

      clickNav('PubMed')

      expect(await screen.findByText('RAG service credential unavailable')).toBeInTheDocument()
      expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
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
      stubRagFetch(401)
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
