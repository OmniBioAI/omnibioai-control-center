import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchReportStatus, triggerGenerate,
  fetchCoverageStatus, triggerCoverageGenerate,
} from '../api'

/**
 * Admin Console: Actions -- report regeneration and coverage refresh.
 * Moved here from the legacy scripts/sections/misc/admin.py static-HTML
 * panel embedded in the ecosystem report page (see
 * docs/admin-console-navigation-move.md for the full rationale). Same
 * two operations, same backend endpoints
 * (/report/generate+/report/status, /coverage/generate+/coverage/status),
 * both still gated server-side by platform.manage_content -- unchanged.
 *
 * No login form here, unlike the legacy panel: this page only renders
 * inside AdminApp, which already requires a real authenticated session
 * via AuthGate before any page (including this one) mounts. api.ts's
 * apiFetch() already attaches that session's token to every call below.
 * These are the two operations the task brief calls out as "safe
 * operational tasks" (regenerate a report, rerun a test-coverage
 * collection) -- neither is destructive, so no additional
 * confirmation/auth step was added beyond what already existed.
 */
type JobStatus = 'idle' | 'running' | 'done' | 'error'

function StatusMessage({ status, message }: { status: JobStatus; message: string }) {
  if (!message) return null
  const color = status === 'error' ? 'var(--red)' : status === 'done' ? 'var(--green, #22c55e)' : 'var(--muted)'
  return <div style={{ fontSize: 12, color, marginTop: 10 }}>{message}</div>
}

export default function ActionsPage() {
  const [reportBusy, setReportBusy] = useState(false)
  const [reportMsg, setReportMsg] = useState('')
  const [reportStatus, setReportStatus] = useState<JobStatus>('idle')

  const [coverageBusy, setCoverageBusy] = useState(false)
  const [coverageMsg, setCoverageMsg] = useState('')
  const [coverageStatus, setCoverageStatus] = useState<JobStatus>('idle')

  const reportTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const coverageTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pollReport = useCallback(async () => {
    try {
      const s = await fetchReportStatus()
      setReportStatus(s.status)
      if (s.status === 'running') {
        setReportMsg('Generating… (2–5 min)')
        reportTimer.current = setTimeout(pollReport, 2000)
      } else if (s.status === 'error') {
        setReportBusy(false)
        setReportMsg(`Error: ${s.message || 'unknown'}`)
      } else if (s.status === 'done') {
        setReportBusy(false)
        setReportMsg('Done -- report regenerated.')
      } else {
        setReportBusy(false)
      }
    } catch (e) {
      setReportBusy(false)
      setReportStatus('error')
      setReportMsg(`Failed to check status: ${String(e)}`)
    }
  }, [])

  const pollCoverage = useCallback(async () => {
    try {
      const s = await fetchCoverageStatus()
      setCoverageStatus(s.status)
      if (s.status === 'running') {
        setCoverageMsg('Running coverage…')
        coverageTimer.current = setTimeout(pollCoverage, 2000)
      } else if (s.status === 'error') {
        setCoverageBusy(false)
        setCoverageMsg(`Error: ${s.message || 'unknown'}`)
      } else if (s.status === 'done') {
        setCoverageBusy(false)
        setCoverageMsg(`Coverage refreshed: ${s.message || ''}`)
      } else {
        setCoverageBusy(false)
      }
    } catch (e) {
      setCoverageBusy(false)
      setCoverageStatus('error')
      setCoverageMsg(`Failed to check status: ${String(e)}`)
    }
  }, [])

  useEffect(() => {
    pollReport()
    pollCoverage()
    return () => {
      if (reportTimer.current) clearTimeout(reportTimer.current)
      if (coverageTimer.current) clearTimeout(coverageTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleRegenerate = async () => {
    setReportBusy(true)
    setReportMsg('Generating report… this takes 2–5 minutes')
    try {
      await triggerGenerate()
      pollReport()
    } catch (e) {
      setReportBusy(false)
      setReportMsg(`Failed to start: ${String(e)}`)
    }
  }

  const handleRefreshCoverage = async () => {
    setCoverageBusy(true)
    setCoverageMsg('Running coverage for control-center…')
    try {
      await triggerCoverageGenerate()
      pollCoverage()
    } catch (e) {
      setCoverageBusy(false)
      setCoverageMsg(`Failed to start: ${String(e)}`)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Actions</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Regenerate the ecosystem report, or refresh control-center's own test coverage on demand.
          Full ecosystem coverage still runs nightly via the scheduled job (see Scheduled Jobs).
        </p>
      </div>

      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '18px 20px', marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 10 }}>Report &amp; Coverage</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            onClick={handleRegenerate}
            disabled={reportBusy}
            style={{
              fontSize: 13, fontWeight: 600, padding: '9px 18px', border: 'none', borderRadius: 8,
              background: reportBusy ? 'rgba(0,229,160,0.4)' : '#00e5a0', color: '#000',
              cursor: reportBusy ? 'not-allowed' : 'pointer',
            }}
          >
            ↻ Regenerate Report
          </button>
          <button
            onClick={handleRefreshCoverage}
            disabled={coverageBusy}
            style={{
              fontSize: 13, fontWeight: 600, padding: '9px 18px', border: 'none', borderRadius: 8,
              background: coverageBusy ? 'rgba(0,229,160,0.4)' : '#00e5a0', color: '#000',
              cursor: coverageBusy ? 'not-allowed' : 'pointer',
            }}
          >
            ↻ Refresh Coverage
          </button>
        </div>
        <StatusMessage status={reportStatus} message={reportMsg} />
        <StatusMessage status={coverageStatus} message={coverageMsg} />
      </div>
    </div>
  )
}
