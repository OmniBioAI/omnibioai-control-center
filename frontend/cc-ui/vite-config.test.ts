// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'

type ProxyEntry = { target: string; rewrite?: (path: string) => string }

async function loadConfig() {
  vi.resetModules()
  return (await import('./vite.config')).default as {
    build: { outDir: string }
    server: { allowedHosts: string[]; proxy: Record<string, ProxyEntry> }
    preview: { allowedHosts: string[]; proxy: Record<string, ProxyEntry> }
  }
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('vite.config', () => {
  it('allows only the explicit staging host in dev and preview', async () => {
    const config = await loadConfig()
    expect(config.server.allowedHosts).toEqual(['admin-staging.omnibioai.org'])
    expect(config.preview.allowedHosts).toEqual(['admin-staging.omnibioai.org'])
  })

  it('defaults every API route to the local Control Center', async () => {
    vi.stubEnv('CONTROL_CENTER_PROXY_TARGET', '')
    const config = await loadConfig()
    const routes = Object.keys(config.server.proxy)
    expect(routes).toEqual(expect.arrayContaining(['/auth', '/sessions', '/platform', '/dashboard', '/orgs', '/organizations']))
    for (const entry of Object.values(config.server.proxy)) expect(entry.target).toBe('http://localhost:7070')
    expect(config.preview.proxy).toBe(config.server.proxy)
  })

  it('retargets every API route from the server-side env var', async () => {
    vi.stubEnv('CONTROL_CENTER_PROXY_TARGET', 'http://cc-backend:7070')
    const config = await loadConfig()
    for (const entry of Object.values(config.server.proxy)) expect(entry.target).toBe('http://cc-backend:7070')
    expect(config.server.proxy['/security-posture/data'].rewrite?.('/security-posture/data')).toBe('/security-posture')
  })

  it('rejects a proxy target that is not an http(s) origin', async () => {
    vi.stubEnv('CONTROL_CENTER_PROXY_TARGET', 'cc-backend:7070/auth')
    await expect(loadConfig()).rejects.toThrow('CONTROL_CENTER_PROXY_TARGET')
  })

  it('keeps the admin/control output directories', async () => {
    vi.stubEnv('VITE_APP_MODE', 'admin')
    expect((await loadConfig()).build.outDir).toBe('dist-admin')
    vi.stubEnv('VITE_APP_MODE', 'control')
    expect((await loadConfig()).build.outDir).toBe('dist-control')
  })
})
