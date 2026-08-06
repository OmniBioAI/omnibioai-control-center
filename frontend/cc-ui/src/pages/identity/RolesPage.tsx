import { useEffect, useState } from 'react'
import {
  fetchMyOrgs, fetchOrgMembers, fetchPlatformOrgs,
  type MyOrg, type OrgMember, type PlatformOrgSummary,
} from '../../organizations'
import {
  fetchOrganizationRoles, fetchOrganizationPermissions,
  createPlatformRole, updatePlatformRole, deletePlatformRole,
  createOrganizationRole, updateOrganizationRole, deleteOrganizationRole,
  type RoleSummary,
} from '../../roles'
import { fetchPermissionRegistry, type PermissionDescriptor } from '../../serviceAccounts'
import { hasPlatformAdminAccess, hasOrgManageAccess } from '../../auth'
import { PageContainer, SectionHeader, ActionToolbar, LoadingState, ErrorState, EmptyState, Card, Button } from '../../components/ui'
import RoleBadge from '../../components/roles/RoleBadge'
import PermissionSelector from '../../components/roles/PermissionSelector'

/**
 * PR11.2 built this as a standalone, read-only view of the role catalog.
 * PR13 (Dynamic Permission Assignment & Enterprise RBAC Activation) is the
 * "separate security review" PR11.2's own docstring deferred create/edit/
 * delete/permission-assignment to -- this page now supports full role
 * catalog CRUD, split by scope exactly the way the backend enforces it:
 *
 *   - Platform Admin: create/edit/delete any platform-wide role (POST/PUT/
 *     DELETE /platform/roles), via omnibioai-auth's manage_all_orgs gate.
 *   - Anyone who manages the selected org (its org_admin, or a Platform
 *     Admin via the synthetic-membership bypass): create/edit/delete that
 *     org's own custom roles (POST/PUT/DELETE /organizations/{id}/roles),
 *     via manage_org. Platform-wide roles stay read-only from this side --
 *     even a Platform Admin edits those through the platform surface
 *     above, not this one, so every mutation has an unambiguous
 *     organization_id in its audit trail.
 *
 * Every gate here (isPlatformAdmin/hasOrgManageAccess) is UX-only, same
 * caveat every other page in this app already documents: it decides which
 * buttons this page *offers*, never whether a request actually succeeds --
 * the backend re-checks independently and rejects (400/403) regardless.
 *
 * Member counts are still computed client-side from GET /orgs/{org_id}/
 * members (best-effort, degrades to "--" on 403 -- unchanged from PR11.2).
 */
interface OrgOption { id: number; name: string }

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const permissionPill: React.CSSProperties = {
  fontSize: 11, fontFamily: 'monospace', padding: '3px 8px', borderRadius: 6,
  background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', color: 'var(--text2)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }
const fieldStyle: React.CSSProperties = {
  fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', width: '100%', boxSizing: 'border-box',
}

// Page-local modal overlay -- same structure ServiceAccountsPage.tsx's own
// Modal already established (no shared components/ui modal exists).
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div
      role="dialog"
      aria-label={title}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 480, maxWidth: '90vw', maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{title}</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

type Scope = 'platform' | { org: number }

function scopeLabel(scope: Scope): string {
  return scope === 'platform' ? 'platform-wide role' : "this organization's custom role"
}

// Create/edit form, shared between the "Create Platform Role" and "Create
// Custom Role" flows (and their edit counterparts) -- the only thing that
// differs is which permission catalog is offered and which roles.ts
// function actually submits, both passed in by the caller.
function RoleForm({
  title, scope, initial, permissions, onClose, onSaved,
}: {
  title: string
  scope: Scope
  initial: RoleSummary | null
  permissions: PermissionDescriptor[]
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [selected, setSelected] = useState<string[]>(initial?.permissions ?? [])
  const [nameError, setNameError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!initial && !name.trim()) { setNameError('Name is required.'); return }
    setNameError(null)
    setSubmitError(null)
    setBusy(true)
    try {
      if (initial) {
        if (scope === 'platform') {
          await updatePlatformRole(initial.id, { permissions: selected, description: description || null })
        } else {
          await updateOrganizationRole(scope.org, initial.id, { permissions: selected, description: description || null })
        }
      } else {
        if (scope === 'platform') {
          await createPlatformRole({ name: name.trim(), permissions: selected, description: description || null })
        } else {
          await createOrganizationRole(scope.org, { name: name.trim(), permissions: selected, description: description || null })
        }
      }
      onSaved()
    } catch (err) {
      setSubmitError(String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {submitError && (
            <div role="alert" style={{ fontSize: 12, color: 'var(--red)', background: 'var(--red-bg)', borderRadius: 8, padding: '8px 12px' }}>
              {submitError}
            </div>
          )}
          {!initial && (
            <div>
              <label style={fieldLabel} htmlFor="role-name">Name</label>
              <input id="role-name" style={fieldStyle} value={name} onChange={e => setName(e.target.value)} />
              {nameError && <div role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{nameError}</div>}
            </div>
          )}
          <div>
            <label style={fieldLabel} htmlFor="role-description">Description (optional)</label>
            <input id="role-description" style={fieldStyle} value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          <div>
            <span style={fieldLabel}>Permissions</span>
            <PermissionSelector allPermissions={permissions} selectedPermissionNames={selected} onChange={setSelected} disabled={busy} />
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={busy}>{busy ? 'Saving…' : initial ? 'Save changes' : `Create ${scopeLabel(scope)}`}</Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

function DeleteConfirm({ roleName, onCancel, onConfirm }: { roleName: string; onCancel: () => void; onConfirm: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
      {err && <span role="alert" style={{ fontSize: 11, color: 'var(--red)' }}>{err}</span>}
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Delete "{roleName}"?</span>
        <Button
          variant="secondary" disabled={busy}
          onClick={async () => {
            setBusy(true); setErr(null)
            try { await onConfirm() } catch (e) { setErr(String(e instanceof Error ? e.message : e)); setBusy(false) }
          }}
        >
          {busy ? 'Deleting…' : 'Confirm'}
        </Button>
        <button onClick={onCancel} disabled={busy} style={{ fontSize: 12, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer' }}>
          Cancel
        </button>
      </span>
    </span>
  )
}

interface Props {
  /** Pre-selects an organization -- set when arriving via "View roles &
   * permissions" from OrganizationDetailPage. */
  initialOrgId?: number | null
}

export default function RolesPage({ initialOrgId }: Props) {
  const [isPlatformAdmin] = useState(() => hasPlatformAdminAccess())
  const [canManageOrg] = useState(() => hasOrgManageAccess())
  const [orgs, setOrgs] = useState<OrgOption[] | null>(null)
  const [orgsErr, setOrgsErr] = useState<string | null>(null)
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(initialOrgId ?? null)

  const [roles, setRoles] = useState<RoleSummary[] | null>(null)
  const [rolesErr, setRolesErr] = useState<string | null>(null)
  const [members, setMembers] = useState<OrgMember[] | null>(null)

  const [platformPermissions, setPlatformPermissions] = useState<PermissionDescriptor[]>([])
  const [orgPermissions, setOrgPermissions] = useState<PermissionDescriptor[]>([])

  const [createScope, setCreateScope] = useState<Scope | null>(null)
  const [editing, setEditing] = useState<{ role: RoleSummary; scope: Scope } | null>(null)
  const [deleting, setDeleting] = useState<RoleSummary | null>(null)

  useEffect(() => {
    setOrgs(null)
    setOrgsErr(null)
    const load = isPlatformAdmin
      ? fetchPlatformOrgs({ pageSize: 100 }).then((r): OrgOption[] => r.items.map((o: PlatformOrgSummary) => ({ id: o.id, name: o.name })))
      : fetchMyOrgs().then((list): OrgOption[] => list.map((o: MyOrg) => ({ id: o.id, name: o.name })))
    load
      .then(list => {
        setOrgs(list)
        setSelectedOrgId(cur => (cur != null && list.some(o => o.id === cur) ? cur : (list[0]?.id ?? null)))
      })
      .catch(e => setOrgsErr(String(e)))
  }, [isPlatformAdmin])

  useEffect(() => {
    if (isPlatformAdmin) fetchPermissionRegistry().then(setPlatformPermissions).catch(() => setPlatformPermissions([]))
  }, [isPlatformAdmin])

  const loadRoles = () => {
    if (selectedOrgId == null) return
    setRoles(null)
    setRolesErr(null)
    fetchOrganizationRoles(selectedOrgId).then(setRoles).catch(e => setRolesErr(String(e)))
  }

  useEffect(() => {
    if (selectedOrgId == null) return
    setMembers(null)
    loadRoles()
    // Best-effort only -- see module docstring. A 403 here just means the
    // member counts below show "--", not an error banner.
    fetchOrgMembers(selectedOrgId).then(setMembers).catch(() => setMembers(null))
    if (canManageOrg) fetchOrganizationPermissions(selectedOrgId).then(setOrgPermissions).catch(() => setOrgPermissions([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrgId])

  const memberCountFor = (roleName: string): number | null =>
    members ? members.filter(m => m.roles.includes(roleName)).length : null

  const canEditRole = (role: RoleSummary): Scope | null => {
    if ((role.organization_id ?? null) === null) return isPlatformAdmin ? 'platform' : null
    if (selectedOrgId != null && role.organization_id === selectedOrgId) return canManageOrg ? { org: selectedOrgId } : null
    return null
  }

  return (
    <PageContainer>
      <SectionHeader
        title="Roles & Permissions"
        description="Each organization's role catalog: platform-wide defaults plus that org's own custom roles. Platform-wide roles are managed by Platform Admins only; an organization's own custom roles are managed by that organization's admins."
        actions={orgs && orgs.length > 0 ? (
          <ActionToolbar>
            <label htmlFor="roles-org-select" style={{ fontSize: 12, color: 'var(--muted)' }}>Organization</label>
            <select
              id="roles-org-select"
              aria-label="Select organization"
              value={selectedOrgId ?? ''}
              onChange={e => setSelectedOrgId(Number(e.target.value))}
              style={selectStyle}
            >
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            {isPlatformAdmin && (
              <Button variant="secondary" onClick={() => setCreateScope('platform')}>Create platform role</Button>
            )}
            {canManageOrg && selectedOrgId != null && (
              <Button variant="primary" onClick={() => setCreateScope({ org: selectedOrgId })}>Create custom role</Button>
            )}
          </ActionToolbar>
        ) : undefined}
      />

      {orgsErr && <ErrorState message={orgsErr} />}
      {!orgsErr && orgs == null && <LoadingState label="Loading organizations…" />}
      {!orgsErr && orgs && orgs.length === 0 && (
        <EmptyState title={isPlatformAdmin ? 'No organizations exist yet.' : "You don't belong to any organization yet."} />
      )}

      {!orgsErr && orgs && orgs.length > 0 && selectedOrgId != null && (
        <>
          {rolesErr && <ErrorState message={rolesErr} />}
          {!rolesErr && roles == null && <LoadingState label="Loading roles…" />}
          {!rolesErr && roles && roles.length === 0 && (
            <EmptyState title="No roles defined for this organization." />
          )}
          {!rolesErr && roles && roles.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {roles.map(role => {
                const count = memberCountFor(role.name)
                const editScope = canEditRole(role)
                const isCustom = (role.organization_id ?? null) !== null
                return (
                  <Card key={role.id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                      <div>
                        <RoleBadge name={role.name} />
                        {isCustom && (
                          <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Custom</span>
                        )}
                        {role.description && (
                          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{role.description}</div>
                        )}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                          {count != null ? `${count} member${count === 1 ? '' : 's'}` : '—'}
                        </div>
                        {editScope && deleting?.id !== role.id && (
                          <>
                            <Button variant="secondary" onClick={() => setEditing({ role, scope: editScope })}>Edit</Button>
                            {isCustom && (
                              <Button variant="ghost" onClick={() => setDeleting(role)}>Delete</Button>
                            )}
                          </>
                        )}
                        {editScope && deleting?.id === role.id && (
                          <DeleteConfirm
                            roleName={role.name}
                            onCancel={() => setDeleting(null)}
                            onConfirm={async () => {
                              if (editScope === 'platform') await deletePlatformRole(role.id)
                              else await deleteOrganizationRole(editScope.org, role.id)
                              setDeleting(null)
                              loadRoles()
                            }}
                          />
                        )}
                      </div>
                    </div>
                    <div style={{
                      marginTop: 12, fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                      textTransform: 'uppercase', letterSpacing: '0.06em',
                    }}>
                      Permissions
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {role.permissions.length
                        ? role.permissions.map(p => <span key={p} style={permissionPill}>{p}</span>)
                        : <span style={{ fontSize: 12, color: 'var(--muted)' }}>No permissions granted.</span>}
                    </div>
                  </Card>
                )
              })}
            </div>
          )}
        </>
      )}

      {createScope && (
        <RoleForm
          title={createScope === 'platform' ? 'Create platform role' : 'Create custom role'}
          scope={createScope}
          initial={null}
          permissions={createScope === 'platform' ? platformPermissions : orgPermissions}
          onClose={() => setCreateScope(null)}
          onSaved={() => { setCreateScope(null); loadRoles() }}
        />
      )}

      {editing && (
        <RoleForm
          title={`Edit ${editing.role.name}`}
          scope={editing.scope}
          initial={editing.role}
          permissions={editing.scope === 'platform' ? platformPermissions : orgPermissions}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); loadRoles() }}
        />
      )}
    </PageContainer>
  )
}
