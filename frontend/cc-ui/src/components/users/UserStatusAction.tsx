import { useState } from 'react'
import { setUserStatus, type PlatformUserDetail } from '../../users'

// Deliberately not sharing OrganizationDetailPage.tsx's own StatusAction
// (Phase 3 PR2) despite the near-identical confirm/reason/cancel
// interaction -- extracting a shared component would mean editing that
// file too, and this PR's own scoping favored zero changes to PR2's
// tested code over removing ~60 lines of duplication. Flagged in this
// PR's implementation report as a reasonable candidate for a future
// shared `StatusChangeAction` component once a third consumer exists.
//
// Suspend/reactivate: platform-admin only, backend-enforced (the 403 a
// non-platform-admin caller gets back is what actually stops them, not
// this button being hidden, which it also is, for UX).
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

interface Props {
  user: PlatformUserDetail
  onChanged: () => void
}

export default function UserStatusAction({ user, onChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)

  const targetStatus = user.status === 'active' ? 'suspended' : 'active'
  const isDestructive = targetStatus === 'suspended'

  const apply = async () => {
    setBusy(true)
    setErr(null)
    try {
      await setUserStatus(user.id, targetStatus, reason.trim() || undefined)
      setConfirming(false)
      setReason('')
      onChanged()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!confirming) {
    return (
      <div>
        {err && <div style={{ marginBottom: 8 }}><ErrBox msg={err} /></div>}
        <button
          onClick={() => setConfirming(true)}
          style={{
            fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
            border: `1px solid ${isDestructive ? 'var(--red)' : 'var(--green-border)'}`,
            background: 'transparent', color: isDestructive ? 'var(--red)' : 'var(--color-success)',
            cursor: 'pointer',
          }}
        >
          {isDestructive ? 'Suspend User' : 'Reactivate User'}
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 420 }}>
      {err && <ErrBox msg={err} />}
      <div style={{ fontSize: 12, color: 'var(--text2)' }}>
        {isDestructive
          ? 'This takes effect immediately: the user’s existing sessions are rejected on their next request or token refresh.'
          : 'This restores normal access -- the user can authenticate again immediately.'}
      </div>
      <input
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="Reason (optional, recorded for this change)"
        aria-label="Reason for status change"
        style={{
          fontSize: 12, padding: '7px 10px', borderRadius: 6,
          border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
        }}
      />
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={apply}
          disabled={busy}
          style={{
            fontSize: 12, fontWeight: 700, padding: '7px 14px', borderRadius: 8, border: 'none',
            background: isDestructive ? 'var(--red)' : 'var(--accent)',
            color: isDestructive ? '#fff' : '#000', cursor: busy ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Applying…' : `Confirm ${isDestructive ? 'suspend' : 'reactivate'}`}
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
  )
}
