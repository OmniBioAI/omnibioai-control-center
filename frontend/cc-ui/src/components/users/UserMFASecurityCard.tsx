import { useState } from 'react'
import { resetUserMFA } from '../../security'
import type { PlatformUserDetail } from '../../users'

// PR11.5.6 (Admin Console Security UI). Same confirm-before-destructive-
// action shape as UserStatusAction.tsx -- Reset MFA is platform-admin
// only, backend-enforced (require_permission(MANAGE_ALL_ORGS),
// PR11.5.4, unmodified); the 403 a non-platform-admin caller gets back
// is what actually stops them, not this button being hidden, which it
// also is (UserDetailPage.tsx is already platform-admin-only).
function ErrBox({ msg }: { msg: string }) {
  return (
    <div role="alert" style={{
      padding: '10px 14px', borderRadius: 8, background: 'var(--red-bg)',
      border: '1px solid var(--red)', color: 'var(--red)', fontSize: 12,
    }}>
      {msg}
    </div>
  )
}

const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const value: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16,
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={value}>{children}</div>
    </div>
  )
}

function formatDateTime(iso: string | null): string {
  if (!iso) return 'Not available'
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// PR11.5.2's device_type vocabulary is currently just "totp" -- display
// label only, mirrors users.ts's authMethodLabel's own fallback-to-raw
// shape for any value outside this map.
const DEVICE_TYPE_LABELS: Record<string, string> = {
  totp: 'Authenticator App',
}
function deviceTypeLabel(deviceType: string): string {
  return DEVICE_TYPE_LABELS[deviceType] ?? deviceType
}

interface Props {
  user: PlatformUserDetail
  onChanged: () => void
}

export default function UserMFASecurityCard({ user, onChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const apply = async () => {
    setBusy(true)
    setErr(null)
    try {
      await resetUserMFA(user.id)
      setConfirming(false)
      onChanged()
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={grid}>
        <Field title="Enabled">{user.mfa_enabled ? 'Yes' : 'No'}</Field>
        <Field title="Primary Method">{user.mfa_primary_method ? deviceTypeLabel(user.mfa_primary_method) : 'Not available'}</Field>
        <Field title="Enabled At">{formatDateTime(user.mfa_enabled_at)}</Field>
        <Field title="Last Verified">{formatDateTime(user.mfa_last_verified_at)}</Field>
      </div>

      {user.mfa_devices.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          <div style={{ ...label, marginBottom: 10 }}>Devices</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {user.mfa_devices.map((d, i) => (
              <div key={i} style={grid}>
                <Field title="Device">{d.label ?? deviceTypeLabel(d.device_type)}</Field>
                <Field title="Added">{formatDateTime(d.created_at)}</Field>
                <Field title="Last Used">{formatDateTime(d.last_used_at)}</Field>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <div style={grid}>
          <Field title="Recovery Codes Remaining">{user.mfa_recovery_codes_remaining}</Field>
        </div>
      </div>

      {/* Never a TOTP secret, QR secret, or a recovery code value --
          PlatformMFADeviceSummary (users.ts) has no such field at all. */}

      {user.mfa_enabled && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          {err && <div style={{ marginBottom: 8 }}><ErrBox msg={err} /></div>}
          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              style={{
                fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
                border: '1px solid var(--red)', background: 'transparent', color: 'var(--red)',
                cursor: 'pointer',
              }}
            >
              Reset MFA
            </button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 420 }}>
              <div style={{ fontSize: 12, color: 'var(--text2)' }}>
                This will remove all MFA devices and invalidate recovery codes. Continue?
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={apply}
                  disabled={busy}
                  style={{
                    fontSize: 12, fontWeight: 700, padding: '7px 14px', borderRadius: 8, border: 'none',
                    background: 'var(--red)', color: '#fff', cursor: busy ? 'not-allowed' : 'pointer',
                  }}
                >
                  {busy ? 'Resetting…' : 'Confirm reset'}
                </button>
                <button
                  onClick={() => { setConfirming(false); setErr(null) }}
                  disabled={busy}
                  style={{
                    fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
                    border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
