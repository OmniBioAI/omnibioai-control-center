import { useEffect, useState } from 'react'
import { getToken } from '../auth'
import { postInvitationToken } from '../organizations'

interface Preview { organization_name: string; email: string; roles: string[]; expires_at: string; existing_user: boolean; mfa_required: boolean }
interface MFASetup { secret: string; otpauth_uri: string }

export default function InvitationAcceptancePage() {
  const [token, setToken] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [mfa, setMfa] = useState<MFASetup | null>(null)
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1))
    const value = fragment.get('token') ?? ''
    window.history.replaceState(null, '', window.location.pathname)
    setToken(value)
    if (!value) { setError('Invitation link is missing its secure token.'); setBusy(false); return }
    postInvitationToken<Preview>('preview', { token: value })
      .then(async data => {
        setPreview(data)
        if (data.mfa_required && !data.existing_user) setMfa(await postInvitationToken<MFASetup>('mfa-setup', { token: value }))
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Invitation could not be verified'))
      .finally(() => setBusy(false))
  }, [])

  const accept = async () => {
    setBusy(true); setError('')
    try {
      if (preview?.existing_user) {
        if (!getToken()) throw new Error('This invitation is for an existing account. Sign in as the invited user, then reopen the invitation link.')
        await postInvitationToken('accept-existing', { token, totp_code: totp || undefined })
      } else {
        await postInvitationToken('accept', { token, password, totp_code: totp || undefined })
      }
      setDone(true)
    } catch (e) { setError(e instanceof Error ? e.message : 'Invitation could not be accepted') }
    finally { setBusy(false) }
  }

  return <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--text)', padding: 24 }}>
    <section style={{ width: 'min(520px, 100%)', padding: 28, borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--border)' }}>
      <h1 style={{ fontSize: 20 }}>Accept Organization Invitation</h1>
      {busy && <p role="status">Verifying invitation…</p>}
      {error && <p role="alert" style={{ color: 'var(--red)' }}>{error}</p>}
      {done && <p role="status">Invitation accepted. Your organization membership is active. You may now sign in and request an eligible license.</p>}
      {!busy && !done && preview && <>
        <p>You are invited to <strong>{preview.organization_name}</strong> as {preview.roles.join(', ')}.</p>
        <p>Invitee: {preview.email}</p>
        {preview.existing_user ? (getToken() ? <form onSubmit={event => { event.preventDefault(); void accept() }} style={{ display: 'grid', gap: 12 }}>
          {preview.mfa_required && <label>Authenticator code<input aria-label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={e => setTotp(e.target.value)} required /></label>}
          <button disabled={busy} type="submit">{busy ? 'Accepting…' : 'Accept invitation'}</button>
        </form> : <p role="status">This invitation is for an existing account. Sign in as the invited user, then reopen the invitation link{preview.mfa_required ? ' and provide a fresh authenticator code' : ''}.</p>) : <form onSubmit={event => { event.preventDefault(); void accept() }} style={{ display: 'grid', gap: 12 }}>
          {mfa && <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8 }}><p>This organization requires MFA. Add this TOTP setup to your authenticator before continuing.</p><p><strong>Setup key:</strong> {mfa.secret}</p><p style={{ overflowWrap: 'anywhere', fontSize: 11 }}>{mfa.otpauth_uri}</p></div>}
          <label>Password<input aria-label="Create password" type="password" required minLength={12} value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label>
          {mfa && <label>Authenticator code<input aria-label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={e => setTotp(e.target.value)} required /></label>}
          <button disabled={busy} type="submit">{busy ? 'Accepting…' : 'Create account and accept invitation'}</button>
        </form>}
      </>}
    </section>
  </main>
}
