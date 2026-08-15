import { useState, useEffect, useCallback } from 'react'
import type { KnownIssue } from '../api'
import { fetchKnownIssues, createKnownIssue, updateKnownIssueStatus, deleteKnownIssue } from '../api'
import { hasAdminAccess } from '../auth'

/**
 * Admin Console: Known Issues. Moved here from the legacy
 * scripts/sections/misc/admin.py static-HTML panel (see
 * docs/admin-console-navigation-move.md). GET /known-issues is open to
 * everyone server-side (read-only); create/update/delete stay gated
 * behind platform.manage_content -- unchanged. The create form and
 * status/delete controls below are additionally hidden for a non-admin
 * caller (hasAdminAccess()), mirroring the legacy panel's own
 * admState.isAdmin check -- the real boundary remains the backend's own
 * require_permission.
 */
const SEV_COLORS: Record<string, { color: string; bg: string }> = {
  high:   { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  medium: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  low:    { color: '#0094ff', bg: 'rgba(0,148,255,0.12)' },
}
const STATUS_COLORS: Record<string, { color: string; bg: string }> = {
  open:         { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  acknowledged: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  resolved:     { color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
}

function Badge({ label, cfg }: { label: string; cfg: { color: string; bg: string } }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, background: cfg.bg, color: cfg.color }}>
      {label}
    </span>
  )
}

const inputStyle: React.CSSProperties = {
  padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6,
  background: 'var(--surface)', color: 'var(--text)', fontFamily: 'inherit',
}

export default function KnownIssuesPage() {
  const [issues, setIssues] = useState<KnownIssue[]>([])
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [area, setArea] = useState('')
  const [severity, setSeverity] = useState('medium')
  const canManage = hasAdminAccess()

  const load = useCallback(async () => {
    try {
      const d = await fetchKnownIssues()
      setIssues(d.issues)
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    if (!title.trim()) { alert('Title is required'); return }
    try {
      await createKnownIssue({ title, description, area, severity })
      setTitle(''); setDescription(''); setArea('')
      load()
    } catch (e) {
      alert(`Failed to create issue: ${String(e)}`)
    }
  }

  const handleStatus = async (id: string, status: string) => {
    try { await updateKnownIssueStatus(id, status); load() } catch (e) { alert(`Failed to update issue: ${String(e)}`) }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this issue?')) return
    try { await deleteKnownIssue(id); load() } catch (e) { alert(`Failed to delete issue: ${String(e)}`) }
  }

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Known Issues</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>Tracked platform issues, visible to everyone.</p>
      </div>

      {error && (
        <div style={{
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 'var(--radius)', padding: '10px 14px', color: '#ef4444', fontSize: 12, marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      {canManage && (
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          padding: '16px 18px', marginBottom: 16,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>New issue</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 520 }}>
            <input value={title} onChange={e => setTitle(e.target.value)} placeholder="title" style={inputStyle} />
            <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="description" rows={3} style={inputStyle} />
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={area} onChange={e => setArea(e.target.value)} placeholder="area (e.g. GPU / Infra)" style={{ ...inputStyle, flex: 1 }} />
              <select value={severity} onChange={e => setSeverity(e.target.value)} style={inputStyle}>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
            <button
              onClick={handleCreate}
              style={{
                alignSelf: 'flex-start', fontSize: 12, fontWeight: 600, padding: '8px 16px', border: 'none',
                borderRadius: 8, background: '#00e5a0', color: '#000', cursor: 'pointer',
              }}
            >
              Add issue
            </button>
          </div>
        </div>
      )}

      {issues.length === 0 && !error && (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>No known issues logged.</div>
      )}

      {issues.map(i => (
        <div key={i.id} style={{
          background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          padding: '14px 16px', marginBottom: 8,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{i.title}</span>
            <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <Badge label={i.severity} cfg={SEV_COLORS[i.severity] ?? SEV_COLORS.low} />
              <Badge label={i.status} cfg={STATUS_COLORS[i.status] ?? STATUS_COLORS.open} />
            </div>
          </div>
          {i.description && <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>{i.description}</div>}
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>{i.area ?? '—'} · opened {i.opened_at ?? '—'}</div>
          {canManage && (
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              <select
                value={i.status}
                onChange={e => handleStatus(i.id, e.target.value)}
                style={{ ...inputStyle, fontSize: 11, padding: '3px 6px' }}
              >
                <option value="open">open</option>
                <option value="acknowledged">acknowledged</option>
                <option value="resolved">resolved</option>
              </select>
              <button
                onClick={() => handleDelete(i.id)}
                style={{
                  fontSize: 11, fontWeight: 600, padding: '4px 10px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--surface)', color: '#ef4444', cursor: 'pointer',
                }}
              >
                Delete
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
