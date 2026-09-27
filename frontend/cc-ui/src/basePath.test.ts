import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiBase, appPath, localPath } from './basePath'

afterEach(() => vi.unstubAllEnvs())

describe('deployment base paths', () => {
  it.each(['/', '/_svc/control/', '/custom/'])('keeps assets, routes and API defaults aligned for %s', base => {
    vi.stubEnv('BASE_URL', base)
    vi.stubEnv('VITE_API_BASE', undefined)
    const prefix = base.replace(/\/$/, '')
    expect(appPath('/evidence')).toBe(`${prefix}/evidence`)
    expect(localPath(`${prefix}/ecosystem`)).toBe('/ecosystem')
    expect(apiBase()).toBe(prefix)
  })
  it('retains the existing explicit API override', () => {
    vi.stubEnv('BASE_URL', '/_svc/control/')
    vi.stubEnv('VITE_API_BASE', '/custom-api/')
    expect(apiBase()).toBe('/custom-api')
  })
  it('uses mounted API paths without reading or clearing the Studio token', async () => {
    vi.stubEnv('BASE_URL', '/_svc/control/')
    vi.stubEnv('VITE_APP_MODE', 'control')
    vi.stubEnv('VITE_API_BASE', undefined)
    vi.resetModules()
    localStorage.setItem('omnibioai_access_token', 'studio-session')
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetcher)
    try {
      const api = await import('./api')
      const overview = await import('./publicOverview')
      await api.fetchHealth()
      await api.fetchReportData()
      await api.fetchReportStatus()
      await overview.fetchShowcase()
      await overview.fetchUptime()
      expect(fetcher.mock.calls.map(call => call[0])).toEqual([
        '/_svc/control/health', '/_svc/control/report/data', '/_svc/control/report/status',
        '/_svc/control/showcase', '/_svc/control/uptime',
      ])
      for (const call of fetcher.mock.calls) expect(call[1]?.headers?.Authorization).toBeUndefined()
      fetcher.mockResolvedValue({ ok: false, status: 401 })
      await expect(api.fetchReportStatus()).rejects.toThrow('401')
      expect(localStorage.getItem('omnibioai_access_token')).toBe('studio-session')
    } finally {
      localStorage.removeItem('omnibioai_access_token')
      vi.unstubAllGlobals()
    }
  })
})
