import { useState } from 'react'
import { login } from '../auth'
import type { SessionUser } from '../auth'
import AdminLogo from './AdminLogo'
import OAuthButtons from './OAuthButtons'

// Mirrors backend/pyproject.toml's version; there's no runtime endpoint
// that exposes it to the frontend, so this is a manually-kept pointer
// rather than a build-time import.
const APP_VERSION = 'v0.1.0'

const ENV_READY = import.meta.env.PROD
const ENV_LABEL = ENV_READY ? 'Production Control Plane' : 'Development'
const ENV_COLOR = ENV_READY ? 'var(--color-success)' : 'var(--amber)'

interface Props {
  onSuccess: (user: SessionUser | null) => void
}

export default function LoginScreen({ onSuccess }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const user = await login(email, password)
      onSuccess(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        fontFamily: 'var(--sans)',
        position: 'relative',
        overflow: 'hidden',
        padding: '24px 16px',
        boxSizing: 'border-box',
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage:
            'linear-gradient(var(--accent-dim) 1px, transparent 1px), ' +
            'linear-gradient(90deg, var(--accent-dim) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at center, black 0%, transparent 70%)',
        }}
      />

      <div style={{ width: '100%', maxWidth: 400, position: 'relative', zIndex: 1 }}>
        {/* ── Admin identity header ── */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 28 }}>
          <AdminLogo size={40} />
          <div style={{ marginTop: 14, textAlign: 'center' }}>
            <div style={{ fontWeight: 700, fontSize: 20, letterSpacing: '-0.01em', lineHeight: 1.2 }}>
              Omni<span style={{ fontWeight: 400, color: 'var(--text)' }}>BioAI</span>{' '}
              <span style={{ color: 'var(--accent)' }}>Admin Portal</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
              Ecosystem Management Console
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14 }}>
            <span
              style={{
                fontFamily: 'var(--mono)',
                fontSize: 11,
                color: 'var(--muted)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '3px 8px',
              }}
            >
              {APP_VERSION}
            </span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                fontFamily: 'var(--mono)',
                fontSize: 11,
                color: ENV_COLOR,
                border: `1px solid ${ENV_COLOR}`,
                borderRadius: 'var(--radius-sm)',
                padding: '3px 8px',
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: ENV_COLOR }} />
              {ENV_LABEL}
            </span>
          </div>
        </div>

        {/* ── Login card ── */}
        <form
          onSubmit={handleSubmit}
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-card)',
            padding: '28px 26px',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 10,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--muted)',
              marginBottom: 6,
            }}
          >
            Email
          </div>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            autoComplete="username"
            style={{ width: '100%', padding: '9px 12px', marginBottom: 16, fontSize: 14 }}
          />

          <div
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 10,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--muted)',
              marginBottom: 6,
            }}
          >
            Password
          </div>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            style={{ width: '100%', padding: '9px 12px', marginBottom: 20, fontSize: 14 }}
          />

          {error && (
            <div
              role="alert"
              style={{
                fontSize: 13,
                color: 'var(--red)',
                background: 'var(--red-bg)',
                border: '1px solid var(--red-border)',
                borderRadius: 'var(--radius-sm)',
                padding: '8px 12px',
                marginBottom: 16,
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: '100%',
              fontSize: 14,
              fontWeight: 600,
              padding: '10px 15px',
              border: 'none',
              borderRadius: 8,
              background: submitting ? 'var(--accent-dim2)' : 'var(--accent)',
              color: '#000',
              cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? 'Authenticating…' : 'Sign In'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '20px 0 16px' }}>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
              Continue with
            </span>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          </div>

          <OAuthButtons />
        </form>

        <div
          style={{
            textAlign: 'center',
            marginTop: 20,
            fontSize: 11,
            fontFamily: 'var(--mono)',
            color: 'var(--muted)',
          }}
        >
          Admin access is permission-based and revocable at any time.
        </div>
      </div>
    </div>
  )
}
