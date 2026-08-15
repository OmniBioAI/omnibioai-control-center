import { Fragment, useState, useEffect, useCallback } from 'react'
import type { CronJob } from '../api'
import { fetchCronJobs, fetchCronJobLog, pauseCronJob, resumeCronJob, updateCronSchedule } from '../api'
import { hasAdminAccess } from '../auth'

/**
 * Admin Console: Scheduled Jobs. Moved here from the legacy
 * scripts/sections/misc/admin.py static-HTML panel (see
 * docs/admin-console-navigation-move.md). GET /cron/jobs and the log
 * endpoint are open to everyone server-side (read-only); pause/resume/
 * reschedule stay gated behind platform.manage_cron -- unchanged. The
 * mutation controls below are additionally hidden for a non-admin
 * caller (hasAdminAccess()) purely as a UX nicety mirroring the legacy
 * panel's own admState.isAdmin check; the real boundary is still the
 * backend's own require_permission, not this check.
 */
const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid var(--border)',
  textAlign: 'left', background: 'rgba(255,255,255,0.03)', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  fontSize: 12, color: 'var(--text2)',
  padding: '10px 14px', borderBottom: '1px solid var(--border)',
  verticalAlign: 'middle',
}

function StatusBadge({ status }: { status: string | null }) {
  const cfg = status === 'ok'
    ? { bg: 'rgba(34,197,94,0.12)', color: '#22c55e' }
    : status === 'error'
      ? { bg: 'rgba(239,68,68,0.12)', color: '#ef4444' }
      : { bg: 'rgba(255,255,255,0.05)', color: 'var(--muted)' }
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, background: cfg.bg, color: cfg.color }}>
      {status ?? '—'}
    </span>
  )
}

function PausedBadge({ paused }: { paused: boolean | null }) {
  if (paused == null) return <span style={{ fontSize: 11, color: 'var(--muted)' }}>unknown</span>
  const cfg = paused
    ? { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', label: 'paused' }
    : { bg: 'rgba(34,197,94,0.12)', color: '#22c55e', label: 'active' }
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, background: cfg.bg, color: cfg.color }}>
      {cfg.label}
    </span>
  )
}

interface LogState { expanded: boolean; loading: boolean; lines: string[]; error: string | null }

export default function ScheduledJobsPage() {
  const [jobs, setJobs] = useState<CronJob[]>([])
  const [error, setError] = useState<string | null>(null)
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<string, string>>({})
  const [logState, setLogState] = useState<Record<string, LogState>>({})
  const canManage = hasAdminAccess()

  const load = useCallback(async () => {
    try {
      const d = await fetchCronJobs()
      setJobs(d.jobs)
      setError(null)
      setScheduleDrafts(prev => {
        const next = { ...prev }
        for (const j of d.jobs) if (!(j.id in next)) next[j.id] = j.schedule
        return next
      })
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  const toggleLog = async (id: string) => {
    const current = logState[id]
    if (current?.expanded) {
      setLogState(s => ({ ...s, [id]: { ...current, expanded: false } }))
      return
    }
    setLogState(s => ({ ...s, [id]: { expanded: true, loading: true, lines: [], error: null } }))
    try {
      const d = await fetchCronJobLog(id)
      setLogState(s => ({ ...s, [id]: { expanded: true, loading: false, lines: d.lines, error: null } }))
    } catch (e) {
      setLogState(s => ({ ...s, [id]: { expanded: true, loading: false, lines: [], error: `Failed to load log: ${String(e)}` } }))
    }
  }

  const doPause = async (id: string) => { try { await pauseCronJob(id); load() } catch (e) { alert(`Failed: ${String(e)}`) } }
  const doResume = async (id: string) => { try { await resumeCronJob(id); load() } catch (e) { alert(`Failed: ${String(e)}`) } }
  const doSaveSchedule = async (id: string) => {
    try { await updateCronSchedule(id, scheduleDrafts[id] ?? ''); load() } catch (e) { alert(`Failed to update schedule: ${String(e)}`) }
  }

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Scheduled Jobs</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>Host crontab jobs -- backups, nightly coverage, sync jobs.</p>
      </div>

      {error && (
        <div style={{
          background: 'var(--red-bg, rgba(239,68,68,0.08))', border: '1px solid var(--red-border, rgba(239,68,68,0.3))',
          borderRadius: 'var(--radius)', padding: '10px 14px', color: 'var(--red, #ef4444)', fontSize: 12, marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Job', 'Schedule', 'State', 'Last Run', 'Last Run At', 'Log', ...(canManage ? ['Controls'] : [])].map(h => (
                <th key={h} style={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && !error && (
              <tr><td colSpan={canManage ? 7 : 6} style={{ ...td, textAlign: 'center', color: 'var(--muted)' }}>loading…</td></tr>
            )}
            {jobs.map(j => {
              const ls = logState[j.id]
              return (
                <Fragment key={j.id}>
                  <tr>
                    <td style={{ ...td, fontWeight: 700, color: 'var(--text)' }}>{j.name}</td>
                    <td style={{ ...td, fontFamily: 'var(--mono)' }}>{j.schedule}</td>
                    <td style={td}><PausedBadge paused={j.paused} /></td>
                    <td style={td}><StatusBadge status={j.last_status} /></td>
                    <td style={td}>{j.last_run_at ? new Date(j.last_run_at).toLocaleString() : 'never'}</td>
                    <td style={td}>
                      <button onClick={() => toggleLog(j.id)} style={smallBtn}>{ls?.expanded ? 'Hide' : 'View'}</button>
                    </td>
                    {canManage && (
                      <td style={td}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <input
                            value={scheduleDrafts[j.id] ?? j.schedule}
                            onChange={e => setScheduleDrafts(s => ({ ...s, [j.id]: e.target.value }))}
                            style={{ width: 100, fontFamily: 'var(--mono)', fontSize: 11, padding: '3px 6px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', color: 'var(--text)' }}
                          />
                          <button onClick={() => doSaveSchedule(j.id)} style={smallBtn}>Save</button>
                          {j.paused
                            ? <button onClick={() => doResume(j.id)} style={smallBtn}>Resume</button>
                            : <button onClick={() => doPause(j.id)} style={smallBtn}>Pause</button>}
                        </div>
                      </td>
                    )}
                  </tr>
                  {ls?.expanded && (
                    <tr>
                      <td colSpan={canManage ? 7 : 6} style={{ padding: '6px 14px 14px', borderBottom: '1px solid var(--border)' }}>
                        {ls.loading ? (
                          <div style={{ fontSize: 11, color: 'var(--muted)' }}>loading log…</div>
                        ) : ls.error ? (
                          <div style={{ fontSize: 11, color: 'var(--red, #ef4444)' }}>{ls.error}</div>
                        ) : ls.lines.length === 0 ? (
                          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Log is empty.</div>
                        ) : (
                          <pre style={{
                            margin: 0, padding: '8px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6,
                            fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.5, maxHeight: 280, overflow: 'auto',
                            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                          }}>
                            {ls.lines.join('\n')}
                          </pre>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const smallBtn: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '4px 10px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', cursor: 'pointer',
}
