import { useState } from 'react'
import { login } from '../auth'

interface Props {
  onSuccess: () => void
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
      await login(email, password)
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)', fontFamily: 'var(--sans)',
    }}>
      <form onSubmit={handleSubmit} style={{
        width: 340, background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)',
        padding: '32px 28px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="30" height="30" style={{ flexShrink: 0 }}>
            <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="#00e5a0" strokeWidth="1.8" />
            <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20"
              stroke="#00e5a0" strokeWidth="1.6" fill="none" strokeLinecap="round" />
            <circle cx="16" cy="15" r="2.2" fill="#00e5a0" />
          </svg>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, color: '#00e5a0', letterSpacing: '-0.01em', lineHeight: 1.2 }}>
              Omni<span style={{ fontWeight: 400, color: 'var(--text)' }}>BioAI</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>Control Center — Admin sign-in</div>
          </div>
        </div>

        <label style={{ display: 'block', fontSize: 12, color: 'var(--text2)', marginBottom: 6 }}>Email</label>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          autoFocus
          style={{
            width: '100%', padding: '9px 12px', marginBottom: 16,
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            color: 'var(--text)', fontSize: 14, fontFamily: 'var(--sans)',
          }}
        />

        <label style={{ display: 'block', fontSize: 12, color: 'var(--text2)', marginBottom: 6 }}>Password</label>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          style={{
            width: '100%', padding: '9px 12px', marginBottom: 20,
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            color: 'var(--text)', fontSize: 14, fontFamily: 'var(--sans)',
          }}
        />

        {error && (
          <div style={{
            fontSize: 13, color: 'var(--red)', background: 'var(--red-bg)',
            border: '1px solid var(--red-border)', borderRadius: 'var(--radius-sm)',
            padding: '8px 12px', marginBottom: 16,
          }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          style={{
            width: '100%', fontSize: 14, fontWeight: 600, padding: '10px 15px',
            border: 'none', borderRadius: 8,
            background: submitting ? 'rgba(0,229,160,0.4)' : '#00e5a0',
            color: '#000', cursor: submitting ? 'not-allowed' : 'pointer',
          }}
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
