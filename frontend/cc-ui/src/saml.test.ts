import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  createOrgSAMLConfig, deleteOrgSAMLConfig, downloadSpMetadata,
  fetchOrgSAMLConfig, updateOrgSAMLConfig, type OrgSAMLConfig,
} from './saml'
import * as auth from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({})), reportUnauthorized: vi.fn() }
})

const CONFIG: OrgSAMLConfig = {
  entity_id: 'https://idp.acme.test/entity',
  sso_url: 'https://idp.acme.test/sso',
  x509_certificate: '-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----',
  attribute_mapping: { email: 'NameID' },
  enabled: false,
  status: 'active',
  created_at: '2026-08-12T00:00:00',
  updated_at: '2026-08-12T00:00:00',
}

describe('fetchOrgSAMLConfig', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('requests the org-scoped path and returns the parsed config', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(CONFIG), { status: 200 }))
    const cfg = await fetchOrgSAMLConfig(7)
    expect(cfg.entity_id).toBe('https://idp.acme.test/entity')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/orgs/7/saml')
  })

  it('throws "<path> <status>" on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }))
    await expect(fetchOrgSAMLConfig(7)).rejects.toThrow('/orgs/7/saml 404')
  })

  it('reports unauthorized on 401', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 401 }))
    await expect(fetchOrgSAMLConfig(7)).rejects.toThrow('401')
    expect(auth.reportUnauthorized).toHaveBeenCalled()
  })
})

describe('createOrgSAMLConfig / updateOrgSAMLConfig', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('POSTs the body and returns the created config', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(CONFIG), { status: 201 }))
    const cfg = await createOrgSAMLConfig(7, {
      entity_id: CONFIG.entity_id, sso_url: CONFIG.sso_url, x509_certificate: CONFIG.x509_certificate,
    })
    expect(cfg.status).toBe('active')
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/orgs/7/saml')
    expect(init?.method).toBe('POST')
  })

  it('prefers the backend detail message over the generic fallback on 409', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'this organization already has a SAML configuration' }), { status: 409 }),
    )
    await expect(
      createOrgSAMLConfig(7, { entity_id: 'x', sso_url: 'https://idp.example.com', x509_certificate: 'cert' }),
    ).rejects.toThrow('this organization already has a SAML configuration')
  })

  it('falls back to "<path> <status>" when the error body has no detail/error field', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({}), { status: 500 }))
    await expect(
      createOrgSAMLConfig(7, { entity_id: 'x', sso_url: 'https://idp.example.com', x509_certificate: 'cert' }),
    ).rejects.toThrow('/orgs/7/saml 500')
  })

  it('PATCHes only the supplied fields', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ...CONFIG, status: 'disabled' }), { status: 200 }))
    await updateOrgSAMLConfig(7, { status: 'disabled' })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/orgs/7/saml')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ status: 'disabled' })
  })

  it('surfaces the backend 422 validation message', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: 'sso_url must use HTTPS' }), { status: 422 }))
    await expect(updateOrgSAMLConfig(7, { sso_url: 'http://idp.example.com' })).rejects.toThrow('sso_url must use HTTPS')
  })
})

describe('deleteOrgSAMLConfig', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('DELETEs the org-scoped path', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))
    await deleteOrgSAMLConfig(7)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/orgs/7/saml')
    expect(init?.method).toBe('DELETE')
  })

  it('throws on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 403 }))
    await expect(deleteOrgSAMLConfig(7)).rejects.toThrow('/orgs/7/saml 403')
  })
})

describe('downloadSpMetadata', () => {
  // Same blob/anchor-click mechanism as compliance.ts's own
  // downloadHipaaReportPdf/Csv, tested the same way -- jsdom's
  // URL.createObjectURL isn't implemented by default, so it's stubbed.
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('downloads from the org-slug-scoped metadata path', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new Blob(['<xml/>']), { status: 200 }))
    await downloadSpMetadata('acme-corp')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/auth/saml/acme-corp/metadata')
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('URL-encodes the org slug', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new Blob(['<xml/>']), { status: 200 }))
    await downloadSpMetadata('acme corp/weird')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/auth/saml/acme%20corp%2Fweird/metadata')
  })

  it('throws on a non-ok response, never silently no-oping', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 503 }))
    await expect(downloadSpMetadata('acme-corp')).rejects.toThrow('/auth/saml/acme-corp/metadata 503')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })
})
