import { useEffect, useState } from 'react'
import { ShieldAlert, ShieldOff } from 'lucide-react'
import {
  createOrgSAMLConfig,
  deleteOrgSAMLConfig,
  downloadSpMetadata,
  fetchOrgSAMLConfig,
  updateOrgSAMLConfig,
  type OrgSAMLConfig,
} from '../../saml'
import { fetchMyOrg, fetchPlatformOrgDetail } from '../../organizations'
import { hasPlatformAdminAccess } from '../../auth'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button, BackLink, SessionExpiredState } from '../../components/ui'
import { formatDate, classifyAuthError } from '../../format'

// PR9 (SAML Admin UI). Structurally mirrors SSOSettingsPage.tsx (PR11.3)
// and OrganizationMFAPolicyPage.tsx (PR11.5.6) deliberately closely --
// same org-label resolution, same loading/denied/not-configured/error
// state machine, same confirm-before-destructive-action shape. No
// break-glass override card here: unlike OrganizationSSOConfig.enforced
// / OrganizationMFAPolicy.required, OrganizationSAMLConfig has no
// enforcement flag with a lockout guard for an override to suspend (see
// PR8's own report) -- there is nothing analogous to build.
const MANAGE_SSO = 'manage_sso'

const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16,
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const value: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }
const fieldStyle: React.CSSProperties = {
  fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', width: '100%', boxSizing: 'border-box',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }
const monoFieldStyle: React.CSSProperties = { ...fieldStyle, fontFamily: 'var(--font-mono, monospace)', fontSize: 12 }

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={value}>{children}</div>
    </div>
  )
}

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

// Discovery status is rendered from the backend's own `status` field
// (pending_verification | active | disabled) -- the same field the
// SAML login/ACS path (omnibioai-auth's saml_acs -> _verify_saml_
// relay_state) actually reads to decide whether a login can succeed at
// all. Unlike SSOSettingsPage's/OrganizationMFAPolicyPage's `enforced`/
// `required`, there is no separate "is SAML *required*" concept here --
// `status` alone is both "is it configured" and "can it be used."
function statusLabel(status: string): string {
  if (status === 'active') return 'Active'
  if (status === 'pending_verification') return 'Pending verification'
  if (status === 'disabled') return 'Disabled'
  return status
}

// ── Current Configuration ──────────────────────────────────────────────

function CurrentConfigCard({ orgLabel, config }: { orgLabel: string; config: OrgSAMLConfig }) {
  const mappingCount = config.attribute_mapping ? Object.keys(config.attribute_mapping).length : 0
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ ...label, marginBottom: 12 }}>Current Configuration</div>
      <div style={grid}>
        <Field title="Organization">{orgLabel}</Field>
        <Field title="Status">{statusLabel(config.status)}</Field>
        <Field title="Entity ID">{config.entity_id}</Field>
        <Field title="IdP SSO URL">{config.sso_url}</Field>
        <Field title="Attribute mappings">{mappingCount > 0 ? `${mappingCount} configured` : 'None'}</Field>
        <Field title="Created">{formatDate(config.created_at)}</Field>
        <Field title="Updated">{formatDate(config.updated_at)}</Field>
      </div>
      {/* `enabled` is intentionally NOT shown as an actionable control
          anywhere on this page -- it is persisted by the backend but not
          read by the SAML login/ACS path (only `status`, above, is).
          Shown here as a plain informational value so the page never
          hides backend state, with an explicit note so it isn't mistaken
          for a working toggle -- see this page's own module comment and
          PR9's final report for the full reasoning. */}
      <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--muted)' }}>
        Enabled flag (informational only, not enforced by login): {config.enabled ? 'true' : 'false'}
      </div>
      {/* Never the certificate's raw PEM body in this summary card -- the
          full text is only ever shown inside the edit form below, where
          an admin explicitly opens it to change it. */}
    </Card>
  )
}

// ── SAML status ──────────────────────────────────────────────────────
//
// The one control on this page with a real security effect: flipping
// `status` between "active" and anything else is what actually
// determines whether GET /auth/saml/{org_slug}/login (and therefore the
// whole SP-initiated login flow) succeeds or 404s -- confirmed in PR8's
// own test suite. Deliberately labeled in terms of that real effect
// ("SAML login is currently..."), not "Enabled/Disabled" (which would
// collide with the inert `enabled` field shown above).

function StatusCard({ orgId, config, onChanged }: { orgId: number; config: OrgSAMLConfig; onChanged: (cfg: OrgSAMLConfig) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<'active' | 'disabled' | null>(null)

  const isActive = config.status === 'active'

  const apply = async (status: 'active' | 'disabled') => {
    setBusy(true)
    setErr(null)
    try {
      const updated = await updateOrgSAMLConfig(orgId, { status })
      setConfirming(null)
      onChanged(updated)
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader title="SAML Login Status" description="Controls whether this organization's SAML login is reachable." />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--text2)' }}>
          SAML login is currently <strong>{statusLabel(config.status)}</strong>.
          {!isActive && (
            <span style={{ color: 'var(--muted)' }}> Members cannot sign in via this organization's IdP while it isn't active.</span>
          )}
        </div>
        {isActive && confirming !== 'disabled' && (
          <Button variant="secondary" disabled={busy} onClick={() => setConfirming('disabled')}>
            Disable SAML Login
          </Button>
        )}
        {!isActive && confirming !== 'active' && (
          <Button variant="primary" disabled={busy} onClick={() => setConfirming('active')}>
            Activate SAML Login
          </Button>
        )}
      </div>

      {confirming === 'disabled' && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 10, maxWidth: 560 }}>
            This immediately stops members from signing in through this organization's SAML IdP.
            The configuration itself is kept, so it can be re-activated at any time.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={() => apply('disabled')}>
              {busy ? 'Disabling…' : 'Confirm: disable SAML login'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {confirming === 'active' && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 10, maxWidth: 560 }}>
            This makes SAML login immediately reachable for this organization. Confirm the Entity
            ID, IdP SSO URL, and certificate below are correct before activating.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={() => apply('active')}>
              {busy ? 'Activating…' : 'Confirm: activate SAML login'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Attribute mapping editor ────────────────────────────────────────────
//
// PR8 accepts attribute_mapping: dict[str, str] | None. No mapping DSL --
// a plain add/remove/edit key-value list, serialized to that object
// shape on submit. Internally keyed by a stable row id (not the map key
// itself, which the admin can freely edit, including to a value that
// transiently collides with another row while typing).

interface MappingRow { id: number; key: string; value: string }

function mappingToRows(mapping: Record<string, string> | null | undefined): MappingRow[] {
  if (!mapping) return []
  return Object.entries(mapping).map(([key, value], i) => ({ id: i, key, value }))
}

function rowsToMapping(rows: MappingRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of rows) {
    if (row.key.trim()) out[row.key.trim()] = row.value
  }
  return out
}

function AttributeMappingEditor({ rows, onChange }: { rows: MappingRow[]; onChange: (rows: MappingRow[]) => void }) {
  const nextId = rows.length > 0 ? Math.max(...rows.map(r => r.id)) + 1 : 0

  const addRow = () => onChange([...rows, { id: nextId, key: '', value: '' }])
  const removeRow = (id: number) => onChange(rows.filter(r => r.id !== id))
  const updateRow = (id: number, field: 'key' | 'value', v: string) =>
    onChange(rows.map(r => (r.id === id ? { ...r, [field]: v } : r)))

  return (
    <div>
      <label style={fieldLabel}>Attribute mapping (optional)</label>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
        Maps this IdP's assertion attribute names to the fields this application expects, e.g. email → NameID.
      </div>
      {rows.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>No mappings configured.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map(row => (
          <div key={row.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              style={fieldStyle}
              value={row.key}
              onChange={e => updateRow(row.id, 'key', e.target.value)}
              placeholder="Field (e.g. email)"
              aria-label="Attribute mapping key"
            />
            <input
              style={fieldStyle}
              value={row.value}
              onChange={e => updateRow(row.id, 'value', e.target.value)}
              placeholder="IdP attribute (e.g. NameID)"
              aria-label="Attribute mapping value"
            />
            <button
              type="button"
              onClick={() => removeRow(row.id)}
              aria-label={`Remove mapping ${row.key || row.id}`}
              style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <button
          type="button"
          onClick={addRow}
          style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer' }}
        >
          + Add mapping
        </button>
      </div>
    </div>
  )
}

// ── Configure SAML Provider ────────────────────────────────────────────

function isValidSsoUrl(v: string): boolean {
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

function isPemCertificate(v: string): boolean {
  return v.includes('-----BEGIN CERTIFICATE-----') && v.includes('-----END CERTIFICATE-----')
}

interface FormState {
  entity_id: string
  sso_url: string
  x509_certificate: string
}

function ConfigureProviderCard({
  orgId, existing, onSaved,
}: { orgId: number; existing: OrgSAMLConfig | null; onSaved: (cfg: OrgSAMLConfig) => void }) {
  const [form, setForm] = useState<FormState>({
    entity_id: existing?.entity_id ?? '',
    sso_url: existing?.sso_url ?? '',
    // Unlike SSOSettingsPage's client_secret, the certificate is public
    // and the backend already returned it in full on GET -- safe (and
    // useful) to pre-fill so an edit doesn't require re-pasting it.
    x509_certificate: existing?.x509_certificate ?? '',
  })
  const [mappingRows, setMappingRows] = useState<MappingRow[]>(mappingToRows(existing?.attribute_mapping))
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [key]: e.target.value }))

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {}
    if (!form.entity_id.trim()) errors.entity_id = 'Entity ID is required.'
    if (!form.sso_url.trim()) errors.sso_url = 'IdP SSO URL is required.'
    else if (!isValidSsoUrl(form.sso_url.trim())) errors.sso_url = 'Enter a valid http(s) URL.'
    if (!form.x509_certificate.trim()) errors.x509_certificate = 'IdP signing certificate is required.'
    else if (!isPemCertificate(form.x509_certificate.trim())) {
      errors.x509_certificate = 'Enter a PEM-encoded certificate (including the BEGIN/END CERTIFICATE lines).'
    }
    return errors
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errors = validate()
    setFieldErrors(errors)
    setSubmitError(null)
    if (Object.keys(errors).length > 0) return

    const attribute_mapping = rowsToMapping(mappingRows)
    const payload = {
      entity_id: form.entity_id.trim(),
      sso_url: form.sso_url.trim(),
      x509_certificate: form.x509_certificate.trim(),
      attribute_mapping: Object.keys(attribute_mapping).length > 0 ? attribute_mapping : null,
    }

    setBusy(true)
    try {
      // Client-side validation above is a UX convenience only -- the
      // backend (PR8's create_saml_config/update_saml_config) performs
      // the real, authoritative validation and its own error message is
      // what's shown on a 422 below, never replaced by this page's own.
      const saved = existing
        ? await updateOrgSAMLConfig(orgId, payload)
        : await createOrgSAMLConfig(orgId, payload)
      onSaved(saved)
    } catch (err) {
      setSubmitError(String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader
        title="Configure SAML Provider"
        description={existing
          ? 'Update this organization’s SAML identity provider.'
          : 'Register this organization’s SAML 2.0 identity provider (Okta, Entra ID, ADFS, ...).'}
      />
      <form onSubmit={submit} noValidate>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {submitError && <ErrBox msg={submitError} />}

          <div>
            <label style={fieldLabel} htmlFor="saml-entity-id">Entity ID</label>
            <input
              id="saml-entity-id"
              style={fieldStyle}
              value={form.entity_id}
              onChange={set('entity_id')}
              placeholder="https://idp.example.com/entity"
              aria-invalid={!!fieldErrors.entity_id}
              aria-describedby={fieldErrors.entity_id ? 'saml-entity-id-error' : undefined}
            />
            {fieldErrors.entity_id && (
              <div id="saml-entity-id-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.entity_id}
              </div>
            )}
          </div>

          <div>
            <label style={fieldLabel} htmlFor="saml-sso-url">IdP SSO URL</label>
            <input
              id="saml-sso-url"
              style={fieldStyle}
              value={form.sso_url}
              onChange={set('sso_url')}
              placeholder="https://idp.example.com/sso"
              aria-invalid={!!fieldErrors.sso_url}
              aria-describedby={fieldErrors.sso_url ? 'saml-sso-url-error' : undefined}
            />
            {fieldErrors.sso_url && (
              <div id="saml-sso-url-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.sso_url}
              </div>
            )}
          </div>

          <div>
            <label style={fieldLabel} htmlFor="saml-certificate">IdP signing certificate</label>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
              The IdP's public X.509 signing certificate (PEM), used to verify assertions it sends. This is not a
              private key -- never paste a private key here.
            </div>
            <textarea
              id="saml-certificate"
              style={{ ...monoFieldStyle, minHeight: 140, resize: 'vertical' }}
              value={form.x509_certificate}
              onChange={set('x509_certificate')}
              placeholder={'-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----'}
              spellCheck={false}
              aria-invalid={!!fieldErrors.x509_certificate}
              aria-describedby={fieldErrors.x509_certificate ? 'saml-certificate-error' : undefined}
            />
            {fieldErrors.x509_certificate && (
              <div id="saml-certificate-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.x509_certificate}
              </div>
            )}
          </div>

          <AttributeMappingEditor rows={mappingRows} onChange={setMappingRows} />

          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? 'Saving…' : existing ? 'Save changes' : 'Create SAML configuration'}
            </Button>
          </div>
        </div>
      </form>
    </Card>
  )
}

// ── Delete configuration ────────────────────────────────────────────────

function DeleteConfigCard({ orgId, onDeleted }: { orgId: number; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleDelete = async () => {
    setBusy(true)
    setErr(null)
    try {
      await deleteOrgSAMLConfig(orgId)
      onDeleted()
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
      setBusy(false)
    }
  }

  return (
    <Card>
      <SectionHeader title="Delete Configuration" description="Removes this organization's SAML configuration entirely." />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}
      {!confirming ? (
        <ActionToolbar>
          <button
            onClick={() => setConfirming(true)}
            style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)', background: 'none', border: '1px solid var(--red)', borderRadius: 8, padding: '7px 15px', cursor: 'pointer' }}
          >
            Delete SAML configuration
          </button>
        </ActionToolbar>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            This permanently removes the Entity ID, SSO URL, certificate, and attribute mapping for this
            organization. Members will no longer be able to sign in via SAML until it is configured again.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleDelete}
              disabled={busy}
              style={{ fontSize: 13, fontWeight: 700, color: '#fff', background: 'var(--red)', border: 'none', borderRadius: 8, padding: '7px 15px', cursor: busy ? 'not-allowed' : 'pointer' }}
            >
              {busy ? 'Deleting…' : 'Confirm: delete configuration'}
            </button>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── SP Metadata ──────────────────────────────────────────────────────
//
// Only a download of the existing, unmodified GET /auth/saml/{org_slug}/
// metadata document -- no client-side XML construction, no IdP metadata
// import, no arbitrary URL fetch. `orgSlug` comes from useOrgLabel's own
// trusted fetchMyOrg/fetchPlatformOrgDetail response below, never from
// user-editable state. Deliberately download-only, not a copyable URL:
// this page's proxy path (control-center's own origin) is not the SP's
// real, publicly-reachable entity/ACS URL an IdP administrator would
// need to reach it externally -- that URL is already baked into the
// downloaded document itself (see PR3/routes_saml.py's entity_id_for/
// acs_url_for) -- so surfacing a second, different URL here would be
// confusing rather than helpful. See PR9's own report for this reasoning.

function MetadataCard({ orgSlug }: { orgSlug: string | null }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleDownload = async () => {
    if (!orgSlug) return
    setBusy(true)
    setErr(null)
    try {
      await downloadSpMetadata(orgSlug)
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader
        title="Service Provider Metadata"
        description="Hand this document to your IdP administrator to complete the trust setup."
      />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}
      <ActionToolbar>
        <Button variant="secondary" disabled={busy || !orgSlug} onClick={handleDownload}>
          {busy ? 'Downloading…' : 'Download SP Metadata'}
        </Button>
      </ActionToolbar>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

interface Props {
  orgId: number
  onBack: () => void
}

/** Resolves a display name (and, uniquely on this page, the org's slug
 * for the metadata download) without inventing a new endpoint -- reuses
 * whichever of organizations.ts's two existing detail fetches the caller
 * can actually reach, exactly like SSOSettingsPage.tsx's/
 * OrganizationMFAPolicyPage.tsx's own useOrgLabel. Best-effort only:
 * failure here doesn't block the SAML config itself from loading, it
 * just falls back to showing the org id and disables the metadata
 * download (which genuinely needs a real slug, not an id). */
function useOrgIdentity(orgId: number): { label: string; slug: string | null } {
  const [label, setLabel] = useState(`Organization #${orgId}`)
  const [slug, setSlug] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    const isPlatformAdmin = hasPlatformAdminAccess()
    const load = isPlatformAdmin ? fetchPlatformOrgDetail(orgId) : fetchMyOrg(orgId)
    load
      .then(org => { if (!cancelled) { setLabel(`${org.name} (${org.slug})`); setSlug(org.slug) } })
      .catch(() => { /* keep the id-based fallback; slug stays null */ })
    return () => { cancelled = true }
  }, [orgId])
  return { label, slug }
}

export default function SAMLSettingsPage({ orgId, onBack }: Props) {
  const [config, setConfig] = useState<OrgSAMLConfig | null>(null)
  const [notConfigured, setNotConfigured] = useState(false)
  const [denied, setDenied] = useState(false)
  const [session, setSession] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const { label: orgLabel, slug: orgSlug } = useOrgIdentity(orgId)

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    setSession(false)
    setNotConfigured(false)
    fetchOrgSAMLConfig(orgId)
      .then(cfg => setConfig(cfg))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'not-found') {
          setNotConfigured(true)
          setConfig(null)
        } else if (kind === 'denied') {
          setDenied(true)
        } else if (kind === 'session') {
          setSession(true)
        } else {
          setError(message)
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [orgId])

  return (
    <div>
      <BackLink label="Back to Organizations" onBack={onBack} />
      <SectionHeader
        title="SAML Settings"
        description="Organization-level enterprise SAML 2.0 SSO configuration."
      />

      {loading && <LoadingState label="Loading SAML configuration…" />}

      {!loading && session && <SessionExpiredState />}

      {!loading && denied && (
        <EmptyState
          icon={ShieldAlert}
          title="Permission denied"
          description={`You don't have ${MANAGE_SSO} for this organization, so its SAML configuration can't be shown here. This is enforced by the backend, not this page.`}
        />
      )}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !session && !denied && !error && (
        <>
          {config && <CurrentConfigCard orgLabel={orgLabel} config={config} />}

          {notConfigured && (
            <div style={{ marginBottom: 16 }}>
              <EmptyState
                icon={ShieldOff}
                title="No SAML configuration"
                description="This organization has no SAML configuration yet. Fill in the form below to register its identity provider."
              />
            </div>
          )}

          {config && <MetadataCard orgSlug={orgSlug} />}

          <ConfigureProviderCard orgId={orgId} existing={config} onSaved={cfg => { setConfig(cfg); setNotConfigured(false) }} />

          {config && (
            <StatusCard orgId={orgId} config={config} onChanged={setConfig} />
          )}

          {config && (
            <DeleteConfigCard orgId={orgId} onDeleted={() => { setConfig(null); setNotConfigured(true) }} />
          )}
        </>
      )}
    </div>
  )
}
