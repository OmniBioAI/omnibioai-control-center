import { useEffect, useState } from 'react'
import {
  createOrgInvitation, fetchOrgInvitations, revokeOrgInvitation,
  type OrganizationInvitation,
} from '../../organizations'
import { fetchOrgRoles, type RoleSummary } from '../../roles'

export default function OrganizationInvitationsCard({ orgId }: { orgId: number }) {
  const [rows, setRows] = useState<OrganizationInvitation[]>([])
  const [roles, setRoles] = useState<RoleSummary[]>([])
  const [email, setEmail] = useState(() => new URLSearchParams(window.location.search).get('inviteEmail') ?? '')
  const [role, setRole] = useState('org_member')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = () => fetchOrgInvitations(orgId).then(setRows).catch(() => setRows([]))
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.has('inviteEmail')) {
      params.delete('inviteEmail')
      const query = params.toString()
      window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`)
    }
    setError(''); setNotice('')
    void refresh()
    fetchOrgRoles(orgId).then(setRoles).catch(() => setRoles([]))
  }, [orgId])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      await createOrgInvitation(orgId, email.trim(), [role])
      setEmail(''); setNotice('Invitation created. The invitee must accept it before membership or license eligibility is granted.')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invitation could not be created')
    } finally { setBusy(false) }
  }

  const revoke = async (id: number) => {
    setBusy(true); setError(''); setNotice('')
    try { await revokeOrgInvitation(orgId, id); setNotice('Invitation revoked.'); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Invitation could not be revoked') }
    finally { setBusy(false) }
  }

  return <section aria-labelledby="org-invitations-title" style={{ marginTop: 16, padding: 18, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--surface)' }}>
    <h3 id="org-invitations-title" style={{ fontSize: 13, color: 'var(--text)', margin: '0 0 12px' }}>Organization Invitations</h3>
    <form onSubmit={submit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      <label style={{ flex: '1 1 220px' }}>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Invitee email</span>
        <input aria-label="Invitee email" type="email" required value={email} onChange={e => setEmail(e.target.value)} style={{ width: '100%', padding: 8, background: 'var(--bg2)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }} />
      </label>
      <label>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Organization role</span>
        <select aria-label="Invitation role" value={role} onChange={e => setRole(e.target.value)} style={{ padding: 9, background: 'var(--bg2)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}>
          {(roles.length ? roles : [{ name: 'org_member' } as RoleSummary]).map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
      </label>
      <button disabled={busy || !email.trim()} style={{ alignSelf: 'end', padding: '9px 14px', border: 0, borderRadius: 6, background: 'var(--accent)', color: 'var(--color-on-accent)', fontWeight: 700, cursor: busy ? 'wait' : 'pointer' }}>{busy ? 'Working…' : 'Invite User'}</button>
    </form>
    <p style={{ fontSize: 11, color: 'var(--muted)' }}>Invitations are email-verified through their single-use link. Membership and license eligibility begin only after acceptance and any required MFA enrollment.</p>
    {error && <div role="alert" style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>{error}</div>}
    {notice && <div role="status" style={{ color: 'var(--accent)', fontSize: 12, marginBottom: 8 }}>{notice}</div>}
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.map(item => <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: 9, borderTop: '1px solid var(--border)', fontSize: 12 }}>
        <span style={{ color: 'var(--text)' }}>{item.email} · {item.roles.join(', ')} · {item.status} · expires {new Date(item.expires_at).toLocaleDateString()}</span>
        {item.status === 'pending' && <button disabled={busy} onClick={() => void revoke(item.id)} aria-label={`Revoke invitation for ${item.email}`} style={{ color: 'var(--red)', background: 'transparent', border: '1px solid var(--border)', borderRadius: 5, padding: '5px 8px' }}>Revoke</button>}
      </div>)}
    </div>
  </section>
}
