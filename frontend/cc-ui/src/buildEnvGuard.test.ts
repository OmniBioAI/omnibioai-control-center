import { describe, it, expect } from 'vitest'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

// Vite inlines VITE_* variables into the PUBLIC JavaScript bundle, and the Docker
// build copies frontend/cc-ui/ wholesale, including any local .env* file. Sibling
// frontends (RAG UI, LIMS, Launcher) once published credentials exactly this way.
// The prebuild guard must fail closed on any VITE_* variable that is not approved
// public configuration and must never print a value. Sentinels here are synthetic.
const SENTINEL = 'OMNIBIOAI_TEST_SECRET_DO_NOT_SHIP'
const ROOT = resolve(__dirname, '..')
const GUARD = join(ROOT, 'scripts', 'check-build-env.cjs')

function runGuard(opts: { env?: Record<string, string>; envFiles?: Record<string, string>; root?: string } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'cc-guard-'))
  try {
    for (const [name, body] of Object.entries(opts.envFiles ?? {})) writeFileSync(join(dir, name), body)
    const clean = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('VITE_')))
    const result = spawnSync(process.execPath, [GUARD, '--root', opts.root ?? dir], {
      env: { ...clean, ...(opts.env ?? {}) } as NodeJS.ProcessEnv, encoding: 'utf8',
    })
    return { status: result.status, output: `${result.stdout}${result.stderr}` }
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

describe('prebuild guard: no secret-like VITE_ variable may reach the browser bundle', () => {
  it('passes on the real repository state (only approved public configuration)', () => {
    expect(runGuard({ root: ROOT }).status).toBe(0)
  })

  it('allows every approved public variable the app reads', () => {
    const env = {
      VITE_API_BASE: 'https://api.example.test', VITE_APP_MODE: 'admin', VITE_ENABLE_OAUTH: 'true',
      VITE_LIMS_SSO_CLIENT_ID: 'public-client-id', VITE_LIMS_SSO_REDIRECT_URI: 'https://lims.example.test/sso/callback',
    }
    expect(runGuard({ env }).status).toBe(0)
  })

  it.each(['VITE_RAGBIO_API_KEY', 'VITE_JUPYTER_TOKEN', 'VITE_SECRET', 'VITE_ANYTHING_NOT_APPROVED'])(
    'fails the build for %s in the environment, naming it but never printing its value', (name) => {
      const { status, output } = runGuard({ env: { [name]: SENTINEL } })
      expect(status).not.toBe(0)
      expect(output).toContain(name)
      expect(output).not.toContain(SENTINEL)
    })

  it.each(['.env', '.env.local', '.env.production', '.env.production.local'])(
    'fails the build for a forbidden variable in %s (the Docker build copies it in)', (file) => {
      const { status, output } = runGuard({ envFiles: { [file]: `VITE_API_BASE=https://ok.example.test\nVITE_RAGBIO_API_KEY=${SENTINEL}\n` } })
      expect(status).not.toBe(0)
      expect(output).toContain('VITE_RAGBIO_API_KEY')
      expect(output).not.toContain(SENTINEL)
    })

  it('ignores non-VITE variables (Vite does not inline them)', () => {
    expect(runGuard({ env: { RAGBIO_API_KEY: SENTINEL, JUPYTER_TOKEN: SENTINEL } }).status).toBe(0)
  })

  it('every build script runs the guard first', () => {
    const scripts = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).scripts as Record<string, string>
    for (const name of ['build', 'build:admin', 'build:control']) {
      expect(scripts[name], name).toMatch(/^node scripts\/check-build-env\.cjs && /)
    }
  })

  it('application source only reads approved variables and never the whole import.meta.env object', () => {
    const allowed = new Set(JSON.parse(readFileSync(join(ROOT, 'scripts', 'public-browser-config.json'), 'utf8')) as string[])
    const sources = walk(join(ROOT, 'src')).filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) && !f.endsWith('.d.ts'))
    for (const file of sources) {
      const text = readFileSync(file, 'utf8')
      expect(/import\.meta\.env(?![.\w])/.test(text), `${file} reads the whole import.meta.env object`).toBe(false)
      for (const [, name] of text.matchAll(/import\.meta\.env\.(VITE_[A-Z0-9_]+)/g)) {
        expect(allowed.has(name), `${file} reads unapproved ${name}`).toBe(true)
      }
    }
  })
})
