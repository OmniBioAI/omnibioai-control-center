import { useState, useEffect } from 'react'
import { fetchConfig, addService } from '../api'

/* ── YAML syntax highlighter ────────────────────────────────── */
function YamlBlock({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <pre style={{ margin: 0, padding: '14px 16px', fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.7, color: 'var(--text)', overflowX: 'auto' }}>
      {lines.map((line, i) => {
        const key = line.match(/^(\s*)([\w-]+)(\s*:)(.*)$/)
        if (key) {
          const [, indent, k, colon, rest] = key
          const isTop = indent === ''
          return (
            <span key={i}>
              {indent}
              <span style={{ color: isTop ? '#2563eb' : '#7c3aed', fontWeight: isTop ? 700 : 400 }}>{k}</span>
              <span style={{ color: '#9ca3af' }}>{colon}</span>
              <span style={{ color: '#059669' }}>{rest}</span>
              {'\n'}
            </span>
          )
        }
        if (line.trimStart().startsWith('#')) {
          return <span key={i} style={{ color: '#9ca3af', fontStyle: 'italic' }}>{line}{'\n'}</span>
        }
        if (line.trimStart().startsWith('-')) {
          return <span key={i} style={{ color: '#d97706' }}>{line}{'\n'}</span>
        }
        return <span key={i}>{line}{'\n'}</span>
      })}
    </pre>
  )
}

/* ── Add service modal ──────────────────────────────────────── */
interface ModalProps { onClose: () => void; onSaved: () => void }

function AddServiceModal({ onClose, onSaved }: ModalProps) {
  const [name, setName]   = useState('')
  const [type, setType]   = useState('http')
  const [url, setUrl]     = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr]     = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true); setErr('')
    try {
      await addService(name.trim(), type, url.trim())
      onSaved(); onClose()
    } catch (e) {
      setErr(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 400, boxShadow: '0 20px 60px rgba(2,6,23,0.18)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>Add Service</span>
          <button onClick={onClose} style={{ fontSize: 18, color: '#9ca3af', lineHeight: 1, cursor: 'pointer' }}>×</button>
        </div>

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <label style={labelStyle}>
            Service Name
            <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. my-api" required style={{ width: '100%', marginTop: 5 }} />
          </label>
          <label style={labelStyle}>
            Type
            <select value={type} onChange={e => setType(e.target.value)} style={{ width: '100%', marginTop: 5 }}>
              <option value="http">http</option>
              <option value="mysql">mysql</option>
              <option value="redis">redis</option>
            </select>
          </label>
          <label style={labelStyle}>
            URL / Target
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="e.g. http://my-api:8080/health" required style={{ width: '100%', marginTop: 5 }} />
          </label>

          {err && (
            <div style={{ fontSize: 11, color: '#dc2626', background: '#fef2f2', borderRadius: 'var(--radius)', padding: '6px 10px' }}>
              {err}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <button
              type="button"
              onClick={onClose}
              style={{ fontSize: 12, padding: '7px 16px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: '#f9fafb', color: '#374151', cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              style={{ fontSize: 12, fontWeight: 600, padding: '7px 16px', border: 'none', borderRadius: 'var(--radius)', background: '#2563eb', color: '#fff', cursor: 'pointer', opacity: saving ? 0.65 : 1 }}
            >
              {saving ? 'Saving…' : 'Add Service'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ── ConfigPage ─────────────────────────────────────────────── */
export default function ConfigPage({ refreshKey }: { refreshKey: number }) {
  const [yaml, setYaml]   = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  const load = async () => {
    try {
      setYaml(await fetchConfig())
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => { load() }, [refreshKey])

  return (
    <div>
      {/* Hero */}
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Configuration</h1>
        <p style={{ fontSize: 13, color: '#6b7280' }}>Live configuration served from the backend</p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>control_center.yaml</div>
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>GET /config</div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ fontSize: 12, fontWeight: 600, padding: '7px 14px', border: 'none', borderRadius: 'var(--radius)', background: '#2563eb', color: '#fff', cursor: 'pointer' }}
        >
          + Add Service
        </button>
      </div>

      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius)', padding: '10px 14px', color: '#dc2626', fontSize: 12, marginBottom: 14 }}>
          {error}
        </div>
      )}

      {yaml != null && (
        <div style={{ background: '#f9fafb', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--surface)' }}>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#9ca3af' }}>YAML</span>
            <span style={{ fontSize: 10, color: '#9ca3af', fontFamily: 'var(--mono)' }}>control_center.yaml</span>
          </div>
          <YamlBlock text={yaml} />
        </div>
      )}

      {showModal && (
        <AddServiceModal onClose={() => setShowModal(false)} onSaved={load} />
      )}
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 11, fontWeight: 600, color: '#374151',
}
