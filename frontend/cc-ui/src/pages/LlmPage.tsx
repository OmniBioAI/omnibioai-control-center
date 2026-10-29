import { useState, useEffect } from 'react'

interface OllamaModel {
  name: string
  size_gb: number
  modified: string
}

interface LlmData {
  ollama: { status: string; url: string; models: OllamaModel[] }
  api_keys: Record<string, { configured: boolean; label: string }>
}

async function fetchLlms(): Promise<LlmData> {
  const r = await fetch('/llms')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export default function LlmPage({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<LlmData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchLlms()
      .then(d => { setData(d); setError(null) })
      .catch(e => setError(String(e)))
  }, [refreshKey])

  const badge = (ok: boolean) => (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 8px',
      borderRadius: 99, letterSpacing: '0.05em',
      background: ok ? 'var(--color-accent-dim)' : 'var(--color-danger-dim)',
      color: ok ? 'var(--color-accent)' : 'var(--color-danger)',
      border: `1px solid ${ok ? 'var(--color-accent-border)' : 'var(--color-danger-border)'}`,
    }}>
      {ok ? 'CONFIGURED' : 'NOT SET'}
    </span>
  )

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>LLMs</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Local Ollama models and cloud API key status
        </p>
      </div>

      {error && (
        <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--radius)', padding: '10px 14px', color: 'var(--red)', fontSize: 12, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Ollama section */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text)' }}>Ollama — Local LLMs</span>
                <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 10, fontFamily: 'var(--mono)' }}>{data.ollama.url}</span>
              </div>
              {badge(data.ollama.status === 'running')}
            </div>
            {data.ollama.models.length === 0 ? (
              <div style={{ padding: '20px 16px', fontSize: 12, color: 'var(--muted)' }}>
                No models installed. Run: <code style={{ fontFamily: 'var(--mono)', color: 'var(--color-accent)' }}>ollama pull llama3</code>
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', background: 'color-mix(in srgb, var(--color-text) 2%, transparent)' }}>
                    {['Model', 'Size', 'Modified'].map(h => (
                      <th key={h} style={{ padding: '8px 16px', textAlign: 'left', fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.ollama.models.map((m, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '10px 16px', fontFamily: 'var(--mono)', color: 'var(--color-purple)' }}>{m.name}</td>
                      <td style={{ padding: '10px 16px', color: 'var(--text2)' }}>{m.size_gb} GB</td>
                      <td style={{ padding: '10px 16px', color: 'var(--muted)' }}>{m.modified}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* API Keys section */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text)' }}>Cloud API Keys</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {Object.entries(data.api_keys).map(([key, info]) => (
                <div key={key} style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, color: 'var(--text)' }}>{info.label}</span>
                  {badge(info.configured)}
                </div>
              ))}
            </div>
          </div>

        </div>
      )}
    </div>
  )
}
