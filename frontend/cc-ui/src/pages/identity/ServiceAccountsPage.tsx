import { useEffect, useState } from 'react'
import { ShieldAlert, Copy, Check } from 'lucide-react'
import {
  fetchApiKeys, createApiKey, revokeApiKey,
  fetchOAuthClients, createOAuthClient, revokeOAuthClient,
  fetchPermissionRegistry,
  type ApiKey, type OAuthClient,
} from '../../serviceAccounts'
import { fetchMyOrg, fetchPlatformOrgDetail } from '../../organizations'
import { hasPlatformAdminAccess } from '../../auth'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button, DataTable, BackLink } from '../../components/ui'
import { formatDate } from '../../format'

const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }
const fieldStyle: React.CSSProperties = {
  fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', width: '100%', boxSizing: 'border-box',
}

function StatusText({ status }: { status: string }) {
  const active = status === 'active'
  return <span style={{ color: active ? 'var(--color-success, #22c55e)' : 'var(--muted)' }}>{active ? 'Active' : 'Revoked'}</span>
}

// ── Generic page-local modal overlay, same structure ConfigPage.tsx's
// own AddServiceModal already established -- there is no shared
// components/ui modal to reuse (confirmed by discovery), so this
// mirrors that existing precedent rather than inventing a new one. ────
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div
      role="dialog"
      aria-label={title}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 440, maxWidth: '90vw', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{title}</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ── Scope picker: two-tier per docs/admin-console-pr11-service-accounts-
// discovery.md §6 -- a real permission-registry catalog for platform
// admins (GET /platform/permissions, manage_all_orgs-gated upstream),
// free text + "seen before in this org" suggestions for everyone else.
// Never a fabricated static list either way. ───────────────────────────
function useScopeSuggestions(existingScopes: string[]): { suggestions: string[]; source: 'registry' | 'existing' } {
  const [registryNames, setRegistryNames] = useState<string[] | null>(null)

  useEffect(() => {
    if (!hasPlatformAdminAccess()) return
    let cancelled = false
    fetchPermissionRegistry()
      .then(perms => { if (!cancelled) setRegistryNames(perms.map(p => p.name)) })
      .catch(() => { /* not a platform admin after all, or transient failure -- fall back silently */ })
    return () => { cancelled = true }
  }, [])

  if (registryNames) return { suggestions: registryNames, source: 'registry' }
  return { suggestions: Array.from(new Set(existingScopes)).sort(), source: 'existing' }
}

function ScopeInput({ scopes, onChange, suggestions, inputId }: {
  scopes: string[]; onChange: (scopes: string[]) => void; suggestions: string[]; inputId: string
}) {
  const [draft, setDraft] = useState('')

  const add = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || scopes.includes(trimmed)) return
    onChange([...scopes, trimmed])
    setDraft('')
  }

  return (
    <div>
      <label style={fieldLabel} htmlFor={inputId}>Scopes (optional)</label>
      {scopes.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {scopes.map(s => (
            <span key={s} style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600,
              padding: '3px 8px', borderRadius: 999, background: 'var(--bg2)', border: '1px solid var(--border)', color: 'var(--text2)',
            }}>
              {s}
              <button
                type="button"
                onClick={() => onChange(scopes.filter(x => x !== s))}
                aria-label={`Remove scope ${s}`}
                style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 12, lineHeight: 1 }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          id={inputId}
          list={`${inputId}-suggestions`}
          style={fieldStyle}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(draft) } }}
          placeholder="e.g. dataset.read"
        />
        <datalist id={`${inputId}-suggestions`}>
          {suggestions.map(s => <option key={s} value={s} />)}
        </datalist>
        <Button type="button" variant="secondary" onClick={() => add(draft)}>Add</Button>
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
        Must be a permission you already hold in this organization -- the backend rejects
        anything else and this form surfaces that rejection verbatim.
      </div>
    </div>
  )
}

// ── Secret reveal: shown exactly once, cleared from state on dismiss. ──
function SecretField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard API unavailable -- the value is still selectable/visible below
    }
  }
  return (
    <div>
      <div style={fieldLabel}>{label}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <code style={{
          flex: 1, fontSize: 12, padding: '8px 10px', borderRadius: 8, background: 'var(--bg)',
          border: '1px solid var(--border)', color: 'var(--text)', overflowX: 'auto', whiteSpace: 'nowrap',
        }}>
          {value}
        </code>
        <Button type="button" variant="secondary" onClick={copy} aria-label={`Copy ${label}`}>
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </Button>
      </div>
    </div>
  )
}

function SecretWarning() {
  return (
    <div style={{
      fontSize: 12, color: 'var(--red)', background: 'var(--red-bg)', border: '1px solid var(--red)',
      borderRadius: 8, padding: '8px 12px', marginBottom: 14,
    }}>
      The secret will only be shown once. Copy it now -- it cannot be displayed again after
      closing this dialog.
    </div>
  )
}

// ── Revoke: inline confirm per row, mirrors OrganizationDetailPage.tsx's
// StatusAction confirm-before-destructive-action shape. ────────────────
function RevokeAction({ name, onConfirm }: { name: string; onConfirm: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer' }}
      >
        Revoke
      </button>
    )
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <button
        onClick={async () => { setBusy(true); await onConfirm(); setBusy(false) }}
        disabled={busy}
        aria-label={`Confirm revoke ${name}`}
        style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)', background: 'none', border: 'none', cursor: busy ? 'not-allowed' : 'pointer' }}
      >
        {busy ? 'Revoking…' : 'Confirm'}
      </button>
      <button
        onClick={() => setConfirming(false)}
        disabled={busy}
        style={{ fontSize: 12, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer' }}
      >
        Cancel
      </button>
    </span>
  )
}

type LoadState<T> = { status: 'loading' } | { status: 'denied'; reason: string } | { status: 'error'; message: string } | { status: 'ready'; items: T[] }

// GET /orgs/{org_id}/api-keys and .../oauth-clients both 404 for a
// non-member (org existence/membership deliberately not distinguished)
// and 403 for a member who lacks the specific permission -- see
// discovery doc §3. Both render as a permission-denied variant here,
// never as a generic ErrorState.
function classify(message: string): 'denied-404' | 'denied-403' | 'error' {
  if (message.endsWith(' 404')) return 'denied-404'
  if (message.endsWith(' 403')) return 'denied-403'
  return 'error'
}

// ── API Keys section ────────────────────────────────────────────────────

function ApiKeysSection({ orgId }: { orgId: number }) {
  const [state, setState] = useState<LoadState<ApiKey>>({ status: 'loading' })
  const [showCreate, setShowCreate] = useState(false)
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null)

  const load = () => {
    setState({ status: 'loading' })
    fetchApiKeys(orgId)
      .then(items => setState({ status: 'ready', items }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404') setState({ status: 'denied', reason: "This organization's API keys aren't accessible to you." })
        else if (kind === 'denied-403') setState({ status: 'denied', reason: "You don't have manage_api_keys for this organization." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId])

  const existingScopes = state.status === 'ready' ? state.items.flatMap(k => k.scopes) : []

  if (state.status === 'loading') return <LoadingState label="Loading API keys…" />
  if (state.status === 'denied') return <EmptyState icon={ShieldAlert} title="Permission denied" description={state.reason} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  return (
    <div>
      <ActionToolbar>
        <Button variant="primary" onClick={() => setShowCreate(true)}>Create API Key</Button>
      </ActionToolbar>
      <div style={{ marginTop: 12 }}>
        <DataTable
          rowKey={k => k.id}
          emptyLabel="No API keys yet."
          rows={state.items}
          columns={[
            { key: 'name', header: 'Name', render: k => k.name ?? '—' },
            { key: 'created', header: 'Created date', render: k => formatDate(k.created_at) },
            { key: 'scopes', header: 'Scopes', render: k => k.scopes.length ? k.scopes.join(', ') : '—' },
            { key: 'last_used', header: 'Last used', render: k => k.last_used_at ? formatDate(k.last_used_at) : 'Never' },
            { key: 'status', header: 'Status', render: k => <StatusText status={k.status} /> },
            {
              key: 'actions', header: 'Actions', render: k => k.status === 'revoked'
                ? <span style={{ color: 'var(--muted)', fontSize: 12 }}>—</span>
                : <RevokeAction name={k.name ?? `key #${k.id}`} onConfirm={async () => { await revokeApiKey(orgId, k.id); load() }} />,
            },
          ]}
        />
      </div>

      {showCreate && (
        <CreateApiKeyModal
          orgId={orgId}
          existingScopes={existingScopes}
          onClose={() => setShowCreate(false)}
          onCreated={(name, key) => { setShowCreate(false); setCreated({ name, key }); load() }}
        />
      )}

      {created && (
        <Modal title="API Key Created" onClose={() => setCreated(null)}>
          <SecretWarning />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SecretField label={`API key for "${created.name}"`} value={created.key} />
            <Button variant="primary" onClick={() => setCreated(null)}>Done</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function CreateApiKeyModal({ orgId, existingScopes, onClose, onCreated }: {
  orgId: number; existingScopes: string[]; onClose: () => void; onCreated: (name: string, key: string) => void
}) {
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [nameError, setNameError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { suggestions } = useScopeSuggestions(existingScopes)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setNameError('Name is required.'); return }
    setNameError(null)
    setSubmitError(null)
    setBusy(true)
    try {
      const result = await createApiKey(orgId, name.trim(), scopes)
      onCreated(result.name ?? name.trim(), result.key)
    } catch (err) {
      setSubmitError(String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Create API Key" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {submitError && (
            <div role="alert" style={{ fontSize: 12, color: 'var(--red)', background: 'var(--red-bg)', borderRadius: 8, padding: '8px 12px' }}>
              {submitError}
            </div>
          )}
          <div>
            <label style={fieldLabel} htmlFor="apikey-name">Name</label>
            <input id="apikey-name" style={fieldStyle} value={name} onChange={e => setName(e.target.value)} />
            {nameError && <div role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{nameError}</div>}
          </div>
          <ScopeInput inputId="apikey-scopes" scopes={scopes} onChange={setScopes} suggestions={suggestions} />
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={busy}>{busy ? 'Creating…' : 'Create API Key'}</Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

// ── OAuth Clients / Service Accounts section ────────────────────────────

function OAuthClientsSection({ orgId }: { orgId: number }) {
  const [state, setState] = useState<LoadState<OAuthClient>>({ status: 'loading' })
  const [showCreate, setShowCreate] = useState(false)
  const [created, setCreated] = useState<{ name: string; client_id: string; client_secret: string } | null>(null)

  const load = () => {
    setState({ status: 'loading' })
    fetchOAuthClients(orgId)
      .then(items => setState({ status: 'ready', items }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404') setState({ status: 'denied', reason: "This organization's service accounts aren't accessible to you." })
        else if (kind === 'denied-403') setState({ status: 'denied', reason: "You don't have manage_oauth_clients for this organization." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId])

  const existingScopes = state.status === 'ready' ? state.items.flatMap(c => c.scopes) : []

  if (state.status === 'loading') return <LoadingState label="Loading service accounts…" />
  if (state.status === 'denied') return <EmptyState icon={ShieldAlert} title="Permission denied" description={state.reason} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  return (
    <div>
      <ActionToolbar>
        <Button variant="primary" onClick={() => setShowCreate(true)}>Create Service Account</Button>
      </ActionToolbar>
      <div style={{ marginTop: 12 }}>
        <DataTable
          rowKey={c => c.id}
          emptyLabel="No service accounts yet."
          rows={state.items}
          columns={[
            { key: 'name', header: 'Client name', render: c => c.name ?? '—' },
            { key: 'client_id', header: 'Client ID', render: c => <code style={{ fontSize: 11 }}>{c.client_id}</code> },
            { key: 'scopes', header: 'Scopes', render: c => c.scopes.length ? c.scopes.join(', ') : '—' },
            { key: 'created', header: 'Created date', render: c => formatDate(c.created_at) },
            { key: 'last_used', header: 'Last used', render: c => c.last_used_at ? formatDate(c.last_used_at) : 'Never' },
            { key: 'status', header: 'Status', render: c => <StatusText status={c.status} /> },
            {
              key: 'actions', header: 'Actions', render: c => c.status === 'revoked'
                ? <span style={{ color: 'var(--muted)', fontSize: 12 }}>—</span>
                : <RevokeAction name={c.name ?? c.client_id} onConfirm={async () => { await revokeOAuthClient(orgId, c.id); load() }} />,
            },
          ]}
        />
      </div>

      {showCreate && (
        <CreateOAuthClientModal
          orgId={orgId}
          existingScopes={existingScopes}
          onClose={() => setShowCreate(false)}
          onCreated={(name, client_id, client_secret) => { setShowCreate(false); setCreated({ name, client_id, client_secret }); load() }}
        />
      )}

      {created && (
        <Modal title="Service Account Created" onClose={() => setCreated(null)}>
          <SecretWarning />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SecretField label="Client ID" value={created.client_id} />
            <SecretField label={`Client secret for "${created.name}"`} value={created.client_secret} />
            <Button variant="primary" onClick={() => setCreated(null)}>Done</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function CreateOAuthClientModal({ orgId, existingScopes, onClose, onCreated }: {
  orgId: number; existingScopes: string[]; onClose: () => void; onCreated: (name: string, clientId: string, clientSecret: string) => void
}) {
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [nameError, setNameError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { suggestions } = useScopeSuggestions(existingScopes)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setNameError('Client name is required.'); return }
    setNameError(null)
    setSubmitError(null)
    setBusy(true)
    try {
      const result = await createOAuthClient(orgId, name.trim(), scopes)
      onCreated(result.name ?? name.trim(), result.client_id, result.client_secret)
    } catch (err) {
      setSubmitError(String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Create Service Account" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {submitError && (
            <div role="alert" style={{ fontSize: 12, color: 'var(--red)', background: 'var(--red-bg)', borderRadius: 8, padding: '8px 12px' }}>
              {submitError}
            </div>
          )}
          <div>
            <label style={fieldLabel} htmlFor="oauth-client-name">Client name</label>
            <input id="oauth-client-name" style={fieldStyle} value={name} onChange={e => setName(e.target.value)} />
            {nameError && <div role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{nameError}</div>}
          </div>
          <ScopeInput inputId="oauth-client-scopes" scopes={scopes} onChange={setScopes} suggestions={suggestions} />
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={busy}>{busy ? 'Creating…' : 'Create Service Account'}</Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

type Tab = 'oauth-clients' | 'api-keys'

interface Props {
  orgId: number
  onBack: () => void
  /** Which tab to land on -- lets OrganizationDetailPage's two distinct
   * links ("Manage Service Accounts" -> OAuth Clients, "Manage API
   * Keys" -> API Keys) open directly on the relevant tab instead of
   * always defaulting to OAuth Clients. Defaults to 'oauth-clients'
   * (the nav item's own org-picker path has no tab preference to pass). */
  initialTab?: Tab
}

/** Resolves a display name for the org header without inventing a new
 * endpoint -- same approach PR11.3's SSOSettingsPage established:
 * reuses whichever of organizations.ts's two existing detail fetches
 * the caller can actually reach. Best-effort only. */
function useOrgLabel(orgId: number): string {
  const [label, setLabel] = useState(`Organization #${orgId}`)
  useEffect(() => {
    let cancelled = false
    const load = hasPlatformAdminAccess() ? fetchPlatformOrgDetail(orgId) : fetchMyOrg(orgId)
    load
      .then(org => { if (!cancelled) setLabel(`${org.name} (${org.slug})`) })
      .catch(() => { /* keep the id-based fallback */ })
    return () => { cancelled = true }
  }, [orgId])
  return label
}

export default function ServiceAccountsPage({ orgId, onBack, initialTab = 'oauth-clients' }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const orgLabel = useOrgLabel(orgId)

  return (
    <div>
      <BackLink label="Back to Organizations" onBack={onBack} />
      <SectionHeader
        title="Service Accounts"
        description={`Organization-level API keys and OAuth service accounts for ${orgLabel}.`}
      />

      <Card style={{ padding: 0, marginBottom: 16 }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'oauth-clients'} onClick={() => setTab('oauth-clients')}>OAuth Clients</TabButton>
          <TabButton active={tab === 'api-keys'} onClick={() => setTab('api-keys')}>API Keys</TabButton>
        </div>
        <div style={{ padding: 20 }}>
          {tab === 'oauth-clients' ? <OAuthClientsSection orgId={orgId} /> : <ApiKeysSection orgId={orgId} />}
        </div>
      </Card>
    </div>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      style={{
        flex: 1, padding: '12px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
        background: 'none', border: 'none', borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
        color: active ? 'var(--text)' : 'var(--muted)',
      }}
    >
      {children}
    </button>
  )
}
