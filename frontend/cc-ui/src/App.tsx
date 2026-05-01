import { useState, useEffect, useCallback } from 'react'
import { fetchSummary, fetchReportStatus, triggerGenerate } from './api'
import Header from './components/Header'
import type { Tab } from './components/Header'
import HealthPage from './pages/HealthPage'
import DockerPage from './pages/DockerPage'
import EcosystemPage from './pages/EcosystemPage'
import ConfigPage from './pages/ConfigPage'

export default function App() {
  const [tab, setTab] = useState<Tab>('health')
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [reportExists, setReportExists] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const poll = async () => {
      try {
        const d = await fetchSummary()
        setOverallStatus(d.overall_status)
      } catch { /* sidebar stays stale */ }
    }
    poll()
    const t = setInterval(poll, 15_000)
    return () => clearInterval(t)
  }, [])

  const pollReport = useCallback(async () => {
    try {
      const s = await fetchReportStatus()
      setReportExists(s.report_exists)
      if (s.status === 'running') {
        setGenerating(true)
        setTimeout(pollReport, 2000)
      } else {
        setGenerating(false)
      }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { pollReport() }, [pollReport])

  const handleGenerate = async () => {
    try {
      await triggerGenerate()
      setGenerating(true)
      setTimeout(pollReport, 2000)
    } catch { /* ignore */ }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' }}>
      <Header
        tab={tab}
        onTab={setTab}
        status={overallStatus}
        generating={generating}
        reportExists={reportExists}
        onRefresh={() => setRefreshKey(k => k + 1)}
        onGenerate={handleGenerate}
      />
      {/* 56px header + 44px tab bar = 100px offset */}
      <div style={{ paddingTop: 100 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '24px 28px 48px' }}>
          {tab === 'health'    && <HealthPage    refreshKey={refreshKey} />}
          {tab === 'docker'    && <DockerPage    refreshKey={refreshKey} />}
          {tab === 'ecosystem' && <EcosystemPage refreshKey={refreshKey} />}
          {tab === 'config'    && <ConfigPage    refreshKey={refreshKey} />}
        </div>
      </div>
    </div>
  )
}
