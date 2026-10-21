import { useEffect, useRef, useState } from 'react'
import { completeMFAChallenge, login, MFAChallengeRequiredError, AuthRateLimitError, MFAResendError, resendMFAEmailCode } from '../auth'
import type { SessionUser } from '../auth'
import AdminLogo from './AdminLogo'


function getEnvironmentLabel() {
  return import.meta.env.VITE_ENVIRONMENT_LABEL?.trim() || 'Development'
}

function environmentTone(label: string): 'development' | 'staging' | 'production' | 'unknown' {
  const normalized = label.toLowerCase()
  if (normalized === 'development' || normalized === 'dev') return 'development'
  if (normalized === 'staging' || normalized === 'stage') return 'staging'
  if (normalized === 'production' || normalized === 'prod') return 'production'
  return 'unknown'
}

interface Props {
  onSuccess: (user: SessionUser | null) => void
}

interface PublicSummary {
  overall_status?: string
}

export default function LoginScreen({ onSuccess }: Props) {
  const appVersion = import.meta.env.VITE_APP_VERSION?.trim() || 'Version unavailable'
  const buildCommit = import.meta.env.VITE_BUILD_COMMIT?.trim().slice(0, 8) || 'local'
  const codeInput = useRef<HTMLInputElement>(null)
  const environmentLabel = getEnvironmentLabel()
  const environment = environmentTone(environmentLabel)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [capsLockOn, setCapsLockOn] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [mfaChallenge, setMfaChallenge] = useState<MFAChallengeRequiredError | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [mfaMethod, setMfaMethod] = useState<'email' | 'totp'>('totp')
  const [resendCooldown, setResendCooldown] = useState(0)
  const [systemStatus, setSystemStatus] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    fetch('/summary', { credentials: 'omit', signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<PublicSummary> : null)
      .then(summary => {
        if (active && summary && typeof summary.overall_status === 'string' && ['UP', 'WARN', 'DOWN'].includes(summary.overall_status)) {
          setSystemStatus(summary.overall_status)
        }
      })
      .catch(() => { /* Public health is optional; keep sign-in usable while it is unavailable. */ })
      .finally(() => window.clearTimeout(timeout))
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [])

  useEffect(() => {
    if (resendCooldown <= 0) return
    const timer = window.setInterval(() => setResendCooldown(value => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [resendCooldown > 0])

  useEffect(() => {
    if (mfaChallenge) codeInput.current?.focus()
  }, [mfaChallenge, mfaMethod])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const user = await login(email, password)
      onSuccess(user)
    } catch (err) {
      if (err instanceof MFAChallengeRequiredError) {
        setMfaChallenge(err)
        if (err.methods.includes('email')) {
          setMfaMethod('email')
          setResendCooldown(60)
        } else {
          setMfaMethod('totp')
        }
        setPassword('')
        setShowPassword(false)
        setCapsLockOn(false)
      } else if (err instanceof AuthRateLimitError) {
        setError('Too many sign-in attempts. Please wait before trying again.')
      } else {
        setError('Unable to sign in. Check your details or contact your platform owner.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mfaChallenge) return
    setError(null)
    setSubmitting(true)
    try {
      const user = mfaMethod === 'email'
        ? await completeMFAChallenge(mfaChallenge.challengeToken, mfaCode, 'email')
        : await completeMFAChallenge(mfaChallenge.challengeToken, mfaCode)
      onSuccess(user)
    } catch (err) {
      if (err instanceof MFAChallengeRequiredError) {
        setMfaChallenge(err)
        setMfaMethod(err.methods.includes('email') ? 'email' : 'totp')
        setMfaCode('')
        setResendCooldown(err.methods.includes('email') ? 60 : 0)
      } else if (err instanceof AuthRateLimitError) {
        setError('Too many verification attempts. Please wait before trying again.')
      } else {
        setError('Unable to verify your code. Check it and try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleResend = async () => {
    if (!mfaChallenge || resendCooldown > 0) return
    setError(null)
    setSubmitting(true)
    try {
      setResendCooldown(await resendMFAEmailCode(mfaChallenge.challengeToken))
      setMfaCode('')
    } catch (err) {
      if (err instanceof MFAResendError && err.retryAfterSeconds) {
        setResendCooldown(err.retryAfterSeconds)
        setError('Too many code requests. Please wait before requesting another code.')
      } else {
        setError('Unable to send a verification code. Please try again later.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="admin-login-page">
      <div aria-hidden="true" className="admin-login-grid" />
      <div className="admin-login-layout">
        <section className="admin-login-intro" aria-label="Admin Console information">
          <AdminLogo size={44} />
          <p className="admin-login-eyebrow">OmniBioAI · Admin Portal</p>
          <h1>Control the ecosystem with confidence.</h1>
          <p className="admin-login-description">Secure access for the people responsible for operating and protecting OmniBioAI.</p>

        </section>

        <div className="admin-login-column">
          <header className="admin-login-header">
            <div className="admin-login-brand">
              <strong>Omni<span>BioAI</span></strong>
              <span className="admin-login-brand-product">Admin Portal</span>
            </div>
            <div className="admin-login-badges">
              <span className="admin-login-version">{appVersion}</span>
              <span className={`admin-environment-badge admin-environment-${environment}`}>
                <span aria-hidden="true" className="admin-environment-dot" />
                {environmentLabel}
              </span>
            </div>
          </header>

          <form className="admin-login-card" onSubmit={mfaChallenge ? handleMfaSubmit : handleSubmit}>
            <div className="admin-login-card-heading">
              <h2>{mfaChallenge ? 'Verify your identity' : 'Sign In'}</h2>
              {!mfaChallenge && <p>Authorized personnel only. Sign-ins are logged.</p>}
            </div>

            {!mfaChallenge ? <>
              <label htmlFor="admin-email">Email address</label>
              <input
                id="admin-email"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
                autoComplete="username"
              />

              <label htmlFor="admin-password">Password</label>
              <div className="admin-password-field">
                <input
                  id="admin-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  onKeyDown={e => setCapsLockOn(e.getModifierState('CapsLock'))}
                  onKeyUp={e => setCapsLockOn(e.getModifierState('CapsLock'))}
                  onBlur={() => setCapsLockOn(false)}
                  required
                  autoComplete="current-password"
                  aria-describedby={capsLockOn ? 'admin-caps-lock' : undefined}
                />
                <button
                  className="admin-password-toggle"
                  type="button"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword(value => !value)}
                >
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
              {capsLockOn && <p id="admin-caps-lock" className="admin-caps-warning" role="status">Caps Lock is on.</p>}
              <a className="admin-login-reset" href="mailto:manish@omnibioai.org?subject=Admin%20Console%20password%20help">
                Contact your platform owner
              </a>
            </> : <>
              <p className="admin-mfa-instructions">
                {mfaMethod === 'email'
                  ? 'Enter the six-digit code sent to the Admin email address. It expires in 5 minutes.'
                  : 'Enter a code from your authenticator app or one of your recovery codes.'}
              </p>
              {mfaChallenge.methods.includes('email') && mfaChallenge.methods.includes('totp') && <div role="group" aria-label="Verification method" className="admin-mfa-methods">
                <button type="button" aria-pressed={mfaMethod === 'email'} onClick={() => { setMfaMethod('email'); setMfaCode(''); setError(null) }}>Email code</button>
                <button type="button" aria-pressed={mfaMethod === 'totp'} onClick={() => { setMfaMethod('totp'); setMfaCode(''); setError(null) }}>Authenticator</button>
              </div>}
              <label htmlFor="admin-mfa-code">Verification code</label>
              <input
                ref={codeInput}
                id="admin-mfa-code"
                value={mfaCode}
                onChange={e => setMfaCode(e.target.value)}
                required
                autoFocus
                autoComplete="one-time-code"
                inputMode={mfaMethod === 'email' ? 'numeric' : undefined}
                pattern={mfaMethod === 'email' ? '[0-9]{6}' : undefined}
                maxLength={mfaMethod === 'email' ? 6 : undefined}
              />
              {mfaMethod === 'email' && <button className="admin-resend" type="button" disabled={submitting || resendCooldown > 0} onClick={handleResend}>
                {resendCooldown > 0 ? `Resend Code (${resendCooldown}s)` : 'Resend Code'}
              </button>}
            </>}

            {error && <div className="admin-login-error" role="alert">{error}</div>}

            <button className="admin-login-submit" type="submit" disabled={submitting}>
              {submitting ? 'Please wait…' : mfaChallenge ? 'Verify' : 'Sign In'}
            </button>

            {mfaChallenge && <button className="admin-back-to-login" type="button" disabled={submitting} onClick={() => { setMfaChallenge(null); setMfaCode(''); setError(null); setResendCooldown(0) }}>
              Back to sign in
            </button>}
          </form>

          {systemStatus && (
            <p className="admin-login-system-status" role="status">
              <span className={`admin-status-dot admin-status-${systemStatus.toLowerCase()}`} aria-hidden="true" />
              Platform status: <strong>{systemStatus}</strong>
              {' · '}<a href="/platform-health">Health</a>
            </p>
          )}
          <p className="admin-login-studio">Looking for OmniBioAI Studio? <a href="https://webstudio.omnibioai.org">Open Studio</a></p>
          <footer className="admin-login-footer">
            <span>{appVersion} · {buildCommit}</span>
            <nav aria-label="Footer links">
              <a href="https://docs.omnibioai.org">Docs</a>
              <a href="https://control.omnibioai.org">Status</a>
              <a href="https://omnibioai.org/privacy">Privacy</a>
              <a href="mailto:manish@omnibioai.org">Support</a>
            </nav>
          </footer>
        </div>
      </div>
    </main>
  )
}
