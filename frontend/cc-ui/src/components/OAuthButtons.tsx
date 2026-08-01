// omnibioai-auth already serves GET /auth/{provider}/login for google/
// github/microsoft (see routes_oauth.py), but control-center's own backend
// only proxies /auth/login and /auth/validate today (routes_auth_proxy.py)
// -- control.omnibioai.org's Cloudflare Tunnel rule bypasses nginx-router
// entirely, so there is no path from this page to auth-service for OAuth
// yet. Buttons render (matches the rest of the ecosystem's login surface)
// but stay disabled until VITE_ENABLE_OAUTH is flipped on, which should
// happen together with adding GET /auth/{provider}/login proxy routes here
// mirroring the existing POST ones.
const OAUTH_READY = (import.meta.env.VITE_ENABLE_OAUTH as string | undefined) === 'true'

type Provider = 'google' | 'microsoft' | 'github'

const PROVIDERS: { id: Provider; label: string; Icon: () => JSX.Element }[] = [
  { id: 'google', label: 'Google', Icon: GoogleIcon },
  { id: 'microsoft', label: 'Microsoft', Icon: MicrosoftIcon },
  { id: 'github', label: 'GitHub', Icon: GitHubIcon },
]

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
      <path fill="#4285F4" d="M15.68 8.18c0-.57-.05-1.11-.14-1.64H8v3.1h4.3a3.68 3.68 0 0 1-1.6 2.42v2h2.58c1.51-1.39 2.4-3.44 2.4-5.88z" />
      <path fill="#34A853" d="M8 16c2.16 0 3.97-.72 5.29-1.94l-2.58-2c-.72.48-1.63.77-2.71.77-2.08 0-3.85-1.41-4.48-3.3H.86v2.07A8 8 0 0 0 8 16z" />
      <path fill="#FBBC05" d="M3.52 9.53a4.8 4.8 0 0 1 0-3.06V4.4H.86a8 8 0 0 0 0 7.2l2.66-2.07z" />
      <path fill="#EA4335" d="M8 3.18c1.17 0 2.23.4 3.06 1.19l2.29-2.29A7.95 7.95 0 0 0 8 0a8 8 0 0 0-7.14 4.4l2.66 2.07C4.15 4.59 5.92 3.18 8 3.18z" />
    </svg>
  )
}

function MicrosoftIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="7.2" height="7.2" fill="#F25022" />
      <rect x="8.8" y="0" width="7.2" height="7.2" fill="#7FBA00" />
      <rect x="0" y="8.8" width="7.2" height="7.2" fill="#00A4EF" />
      <rect x="8.8" y="8.8" width="7.2" height="7.2" fill="#FFB900" />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="var(--muted)" xmlns="http://www.w3.org/2000/svg">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.5 7.5 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

export default function OAuthButtons() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {PROVIDERS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          disabled={!OAUTH_READY}
          title={OAUTH_READY ? undefined : 'Single sign-on is not yet enabled for control.omnibioai.org'}
          onClick={() => {
            window.location.href = `/auth/${id}/login`
          }}
          style={{
            width: '100%',
            padding: '9px 0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            background: 'transparent',
            color: OAUTH_READY ? 'var(--text2)' : 'var(--muted)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 13,
            cursor: OAUTH_READY ? 'pointer' : 'not-allowed',
            opacity: OAUTH_READY ? 1 : 0.55,
          }}
        >
          <Icon />
          Continue with {label}
        </button>
      ))}
    </div>
  )
}
