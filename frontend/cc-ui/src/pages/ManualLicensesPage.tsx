import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { Button, Card, EmptyState, ErrorState, LoadingState, SectionHeader } from '../components/ui'
import {
  fetchLicenseHistory, fetchLicensePolicy, fetchLicenses, issueLicense, lookupLicenseIdentity, renewLicense, revokeLicense,
  type IssueLicenseRequest, type LicenseHistoryItem, type LicenseIdentity, type LicenseMetadata, type LicensePersona, type LicensePolicy,
} from '../licenses'

const field: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: '9px 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }
const label: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 5 }

type LoadFailures = {
  policy: string | null
  registry: string | null
}

function describeLoadFailure(
  resource: 'license policy' | 'license registry',
  expectedPath: string,
  failure: unknown,
): string {
  const error = failure as Error & { path?: string; status?: number }
  const path = error.path ?? expectedPath
  return error.status
    ? `Couldn’t load the ${resource} (${error.status} from ${path}).`
    : `Couldn’t load the ${resource} (request to ${path} failed).`
}

export default function ManualLicensesPage() {
  const [policy, setPolicy] = useState<LicensePolicy | null>(null)
  const [licenses, setLicenses] = useState<LicenseMetadata[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailures, setLoadFailures] = useState<LoadFailures>({ policy: null, registry: null })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [identityBusy, setIdentityBusy] = useState(false)
  const [identity, setIdentity] = useState<LicenseIdentity | null>(null)
  const [identityLookupDenied, setIdentityLookupDenied] = useState(false)
  const [identityMessage, setIdentityMessage] = useState<{ message: string; kind: 'success' | 'error'; invite: boolean } | null>(null)
  const [oneTimeKey, setOneTimeKey] = useState<string | null>(null)
  const [history, setHistory] = useState<{ id: number; items: LicenseHistoryItem[] } | null>(null)
  const [form, setForm] = useState<IssueLicenseRequest>({
    full_name: '', email: '', persona: 'developer', validity_days: 0, organization_id: 0,
    confirm_role_change: false, confirm_replace_existing: false,
  })
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID())

  const checkIdentity = async () => {
    const email = form.email.trim()
    const organizationId = Number(form.organization_id)
    if (!email || !Number.isInteger(organizationId) || organizationId < 1) {
      setIdentity(null)
      setIdentityMessage({ message: 'Enter a valid email and organization ID before checking eligibility.', kind: 'error', invite: false })
      return
    }

    setIdentityBusy(true)
    setIdentity(null)
    setIdentityLookupDenied(false)
    setIdentityMessage(null)
    setError(null)
    try {
      const resolved = await lookupLicenseIdentity(email, organizationId)
      setIdentity(resolved)
      setForm(current => ({ ...current, email: resolved.email }))
      setIdentityMessage({ message: `Verified active identity and organization membership for ${resolved.email}.`, kind: 'success', invite: false })
    } catch (e) {
      const failure = e as Error & { code?: string }
      if (failure.code === 'identity_missing') {
        setIdentityMessage({ message: failure.message, kind: 'error', invite: true })
      } else if (failure.code === 'identity_membership_required') {
        setIdentityMessage({ message: failure.message, kind: 'error', invite: true })
      } else if (failure.code === 'identity_inactive') {
        setIdentityMessage({ message: failure.message, kind: 'error', invite: false })
      } else if (failure.message.includes('403')) {
        // The designated legacy Admin can issue licenses but intentionally
        // cannot enumerate the cross-tenant user directory. Keep the
        // existing issuance route available in this case; Auth remains the
        // authority and rejects missing/inactive/cross-tenant identities.
        setIdentityLookupDenied(true)
        setIdentityMessage({ message: 'Identity directory access is not granted to this account. You may submit the request; Auth will verify account and organization eligibility before issuance.', kind: 'error', invite: false })
      } else {
        setIdentityMessage({ message: 'Identity verification failed. Retry, or contact an administrator if the service remains unavailable.', kind: 'error', invite: false })
      }
    } finally {
      setIdentityBusy(false)
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    setLoadFailures({ policy: null, registry: null })
    setError(null)

    const [policyResult, registryResult] = await Promise.allSettled([
      fetchLicensePolicy(),
      fetchLicenses(),
    ])
    const failures: LoadFailures = { policy: null, registry: null }

    if (policyResult.status === 'fulfilled') {
      const nextPolicy = policyResult.value
      setPolicy(nextPolicy)
      setForm(current => ({
        ...current,
        validity_days: current.validity_days || nextPolicy.validity_days[0] || 0,
      }))
    } else {
      setPolicy(null)
      failures.policy = describeLoadFailure(
        'license policy', '/platform/licenses/policy', policyResult.reason,
      )
    }

    if (registryResult.status === 'fulfilled') {
      setLicenses(registryResult.value.items)
    } else {
      setLicenses(null)
      failures.registry = describeLoadFailure(
        'license registry', '/platform/licenses', registryResult.reason,
      )
    }

    setLoadFailures(failures)
    setLoading(false)
  }, [])
  useEffect(() => { load() }, [load])

  const loadError = [loadFailures.policy, loadFailures.registry].filter(Boolean).join(' ')
  const formBlockedReason = loading
    ? 'License policy and registry data are still loading.'
    : loadError
      ? `${loadError} Issuance is disabled until both requests succeed.`
      : !policy?.issuance_enabled
        ? 'The current license policy does not permit issuance.'
        : null

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (formBlockedReason) {
      setError(`License issuance is disabled. ${formBlockedReason}`)
      return
    }
    setBusy(true); setError(null); setOneTimeKey(null)
    try {
      const result = await issueLicense(form, idempotencyKey)
      setOneTimeKey(result.key)
      setIdempotencyKey(crypto.randomUUID())
      setForm(current => ({ ...current, full_name: '', email: '', confirm_role_change: false, confirm_replace_existing: false }))
      await load()
    } catch (e) {
      const coded = e as Error & { code?: string }
      if (coded.code === 'role_change_confirmation_required') setForm(current => ({ ...current, confirm_role_change: true }))
      if (coded.code === 'active_license_confirmation_required') setForm(current => ({ ...current, confirm_replace_existing: true }))
      if (coded.code === 'provisioning_required' || coded.code === 'identity_membership_required') {
        setIdentity(null)
        setIdentityMessage({ message: coded.message, kind: 'error', invite: true })
      } else setError(coded.message)
    } finally { setBusy(false) }
  }

  if (loading && !policy && !licenses) return <LoadingState label="Loading license policy and registry…" />
  return <div>
    <SectionHeader title="License Management" description="Issue identity-bound licenses. Full keys are shown once and are never available from history." />
    {(loadError || error) && <div role="alert" style={{ marginBottom: 14 }}><ErrorState message={loadError || error || ''} onRetry={loadError ? load : undefined} /></div>}
    {oneTimeKey && <Card><h2>New license key — copy now</h2>
      <div role="status" style={{ padding: 16 }}>
        <code style={{ fontSize: 18 }}>{oneTimeKey}</code>
        <Button style={{ marginLeft: 12 }} onClick={() => navigator.clipboard.writeText(oneTimeKey)}>Copy key</Button>
        <p style={{ color: 'var(--muted)', fontSize: 12 }}>This key will disappear when you leave or issue another license.</p>
      </div>
    </Card>}
    <Card><h2>Issue New License</h2>
      {formBlockedReason && <p id="license-form-disabled-reason" role="status" style={{ padding: '0 16px', color: 'var(--yellow)' }}>
        License issuance is unavailable: {formBlockedReason}
      </p>}
      <form onSubmit={submit} aria-describedby={formBlockedReason ? 'license-form-disabled-reason' : undefined}>
        <fieldset aria-label="Issue New License fields" disabled={Boolean(formBlockedReason)} style={{ padding: 16, margin: 0, border: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 14 }}>
        <div><label htmlFor="license-full-name" style={label}>Full name</label><input id="license-full-name" required style={field} value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></div>
        <div>
          <label htmlFor="license-email" style={label}>Existing identity email</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id="license-email" required type="email" style={field} value={form.email} aria-describedby="license-identity-status" onChange={e => { setForm({ ...form, email: e.target.value }); setIdentity(null); setIdentityLookupDenied(false); setIdentityMessage(null) }} />
            <Button type="button" variant="secondary" onClick={checkIdentity} disabled={identityBusy || !form.email.trim() || !form.organization_id}>
              {identityBusy ? 'Checking…' : 'Check identity'}
            </Button>
          </div>
          {identity && <label htmlFor="license-identity-selection" style={{ ...label, marginTop: 8 }}>Verified identity</label>}
          {identity && <select id="license-identity-selection" aria-label="Select verified identity" style={field} value={identity.user_id} onChange={() => undefined}>
            <option value={identity.user_id}>{identity.email} · active in organization {identity.organization_id}</option>
          </select>}
          {identityMessage && <div id="license-identity-status" role={identityMessage.kind === 'error' ? 'alert' : 'status'} style={{ marginTop: 8, color: identityMessage.kind === 'error' ? 'var(--red)' : 'var(--accent)' }}>
            {identityMessage.message}
            {identityMessage.invite && <div style={{ marginTop: 6 }}>
              <a href={`/organizations/${form.organization_id}?inviteEmail=${encodeURIComponent(form.email.trim())}`} aria-label="Invite User through organization onboarding" style={{ color: 'var(--accent)', fontWeight: 700 }}>Invite User</a>
              <span> through the organization onboarding workflow, then re-check eligibility.</span>
            </div>}
          </div>}
        </div>
        <div><label htmlFor="license-persona" style={label}>Role</label><select id="license-persona" style={field} value={form.persona} onChange={e => setForm({ ...form, persona: e.target.value as LicensePersona })}>
          {policy?.personas.map(p => <option key={p} value={p}>{p === 'developer' ? 'Developer' : 'Application User'}</option>)}
        </select></div>
        <div><label htmlFor="license-validity" style={label}>License validity</label><select id="license-validity" required style={field} value={form.validity_days} onChange={e => setForm({ ...form, validity_days: Number(e.target.value) })}>
          {!policy?.validity_days.length && <option value={0}>Policy not configured</option>}
          {policy?.validity_days.map(days => <option key={days} value={days}>{days} days</option>)}
        </select></div>
        <div><label htmlFor="license-organization" style={label}>Organization ID</label><input id="license-organization" required min={1} type="number" style={field} value={form.organization_id || ''} onChange={e => { setForm({ ...form, organization_id: Number(e.target.value) }); setIdentity(null); setIdentityLookupDenied(false); setIdentityMessage(null) }} /></div>
        <div style={{ alignSelf: 'end' }}><Button type="submit" aria-label="Issue License" aria-busy={busy} disabled={Boolean(formBlockedReason) || busy || identityBusy || (!identity && !identityLookupDenied) || !policy?.issuance_enabled}>{busy ? 'Issuing…' : <><Plus size={15} aria-hidden="true" />Issue License</>}</Button></div>
        {(form.confirm_role_change || form.confirm_replace_existing) && <div style={{ gridColumn: '1 / -1', fontSize: 12, color: 'var(--yellow)' }}>
          Review and submit again to confirm: {form.confirm_role_change && 'IAM role assignment'}{form.confirm_role_change && form.confirm_replace_existing && ' and '}{form.confirm_replace_existing && 'replacement of an active license'}.
        </div>}
        </fieldset>
      </form>
    </Card>
    <div style={{ marginTop: 18 }}><Card><h2>License Registry</h2>
      {loadFailures.registry ? <EmptyState title="License registry unavailable" /> : !licenses ? <LoadingState label="Loading licenses…" /> : !licenses.length ? <EmptyState title="No licenses found" /> :
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}><thead><tr>
          {['Key','Name / email','Role','Organization','Status','Expires','Actions'].map(h => <th key={h} style={{ textAlign: 'left', padding: 10, borderBottom: '1px solid var(--border)' }}>{h}</th>)}
        </tr></thead><tbody>{licenses.map(item => <tr key={item.id}>
          <td style={{ padding: 10 }}><code>{item.masked_key}</code></td><td style={{ padding: 10 }}>{item.recipient_name}<br />{item.email}</td>
          <td style={{ padding: 10 }}>{item.persona?.replace('_', ' ') || 'Legacy / unmapped'}</td><td style={{ padding: 10 }}>{item.organization_id ?? 'Legacy'}</td>
          <td style={{ padding: 10 }}>{item.status}</td><td style={{ padding: 10 }}>{item.expires_at ? new Date(item.expires_at).toLocaleString() : 'No expiry'}</td>
          <td style={{ padding: 10, display: 'flex', gap: 6 }}>
            <Button variant="secondary" onClick={async () => setHistory({ id: item.id, items: (await fetchLicenseHistory(item.id)).items })}>History</Button>
            {item.status === 'active' && <Button variant="secondary" onClick={async () => { const reason = prompt('Revocation reason'); if (reason) { await revokeLicense(item.id, reason); await load() } }}>Revoke</Button>}
            {item.status !== 'revoked' && policy?.validity_days[0] && <Button variant="secondary" onClick={async () => { await renewLicense(item.id, policy.validity_days[0]); await load() }}>Renew +{policy.validity_days[0]}d</Button>}
          </td>
        </tr>)}</tbody></table></div>}
      {history && <div style={{ padding: 16, borderTop: '1px solid var(--border)' }}><strong>License {history.id} history</strong>
        <ul>{history.items.map(item => <li key={item.id}>{item.created_at ? new Date(item.created_at).toLocaleString() : ''} — {item.event_type}</li>)}</ul>
      </div>}
    </Card></div>
  </div>
}
