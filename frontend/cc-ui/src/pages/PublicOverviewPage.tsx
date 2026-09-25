import { useEffect, useState, type ReactNode } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchHealth } from '../api'
import { Card } from '../components/ui'
import {
  Badge, Grid, Loading, Section, Tile, Unavailable, daysAgo, fmt, useLoad, type Load,
} from '../components/publicShowcase'
import {
  CATALOG_SNAPSHOT,
  fetchAiAndWorkflow, fetchBackends, fetchOpenIssues, fetchPublicStats,
  fetchReferenceStatus, fetchUptime, fetchUsage,
  type BackendStatus, type PublicAiAndWorkflow, type PublicIssue, type PublicStats,
  type ReferenceStatus, type UptimeSummary, type UsageStatus,
} from '../publicOverview'

/**
 * Public Platform Overview -- the default tab of the anonymous
 * control.omnibioai.org build. A showcase assembled only from routes that
 * already answer without a token (see publicOverview.ts); each section
 * loads on its own, so one unavailable backend shows "unavailable" in its
 * own card instead of blanking the page. Figures are labelled with where
 * they come from and when; nothing here is placeholder data.
 */

// ── Sections ─────────────────────────────────────────────────────────────

function StatusStrip({ refreshKey, stats }: { refreshKey: number; stats: Load<PublicStats> }) {
  const [status, setStatus] = useState<'checking' | 'ok' | 'down'>('checking')
  const [checkedAt, setCheckedAt] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    const load = () => fetchHealth().then(
      r => { if (!cancelled) { setStatus(r.status === 'ok' ? 'ok' : 'down'); setCheckedAt(new Date().toLocaleTimeString()) } },
      () => { if (!cancelled) { setStatus('down'); setCheckedAt(new Date().toLocaleTimeString()) } },
    )
    load()
    const t = setInterval(load, 30_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [refreshKey])
  const color = status === 'ok' ? 'var(--green)' : status === 'down' ? 'var(--red)' : 'var(--muted)'
  const label = status === 'ok' ? 'Control center online' : status === 'down' ? 'Control center unreachable' : 'Checking…'
  const generated = stats.state === 'ok' ? stats.data.generated_at : null
  return (
    <Card style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 24px' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, color }}>
        <span style={{ width: 9, height: 9, borderRadius: '50%', background: color }} />{label}
      </span>
      {checkedAt && <span style={{ fontSize: 12, color: 'var(--muted)' }}>Last checked {checkedAt}</span>}
      {generated && (
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          Ecosystem report generated {daysAgo(generated)} ({new Date(generated).toLocaleString()})
        </span>
      )}
    </Card>
  )
}

function dayColor(pct: number | null): string {
  if (pct === null) return 'var(--border)'
  if (pct >= 99.5) return 'var(--green)'
  if (pct >= 95) return 'var(--amber)'
  return 'var(--red)'
}

function UptimeSection({ uptime }: { uptime: Load<UptimeSummary> }) {
  let body: ReactNode
  if (uptime.state === 'loading') body = <Loading />
  else if (uptime.state === 'error') body = <Unavailable what="Uptime history" />
  else if (uptime.data.services.length === 0) body = (
    <Card><span style={{ fontSize: 13, color: 'var(--muted)' }}>Uptime history is not being published yet.</span></Card>
  )
  else body = (
    <Card>
      {uptime.data.services.map((svc, n) => (
        <div key={svc.label} style={{ padding: '8px 0', borderTop: n ? '1px solid var(--border)' : 'none' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
            <span style={{ color: 'var(--text)', fontWeight: 600 }}>{svc.label}</span>
            <span style={{ color: 'var(--muted)' }}>
              {svc.overall_pct === null ? 'no data yet' : `${svc.overall_pct}% available`}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 2 }} role="img"
            aria-label={`${svc.label}: daily availability over ${uptime.data.window_days} days`}>
            {svc.days.map(d => (
              <span key={d.date}
                title={`${d.date}: ${d.availability_pct === null ? 'no data' : `${d.availability_pct}%`}`}
                style={{ flex: 1, height: 22, borderRadius: 2, background: dayColor(d.availability_pct) }} />
            ))}
          </div>
        </div>
      ))}
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
        {uptime.data.window_days} days, oldest on the left. Sampled every {Math.round(uptime.data.sample_seconds / 60)} minutes by the control center's own health checks; grey means no samples that day.
      </div>
    </Card>
  )
  return <Section title="Uptime" description="Daily availability of the platform's main services.">{body}</Section>
}

function CatalogSection() {
  return (
    <Section
      title="Platform at a glance"
      description={`Registered in source, from the documentation's generated catalogs (snapshot ${CATALOG_SNAPSHOT.asOf}). Registered is not the same as tested or deployed.`}
    >
      <Grid>
        {CATALOG_SNAPSHOT.items.map(i => <Tile key={i.label} label={i.label} value={i.value} href={i.href} />)}
      </Grid>
    </Section>
  )
}

function ActivitySection({ usage }: { usage: Load<UsageStatus> }) {
  let body: ReactNode
  if (usage.state === 'loading') body = <Loading />
  else if (usage.state === 'error') body = <Unavailable what="Usage data" />
  else {
    const u = usage.data
    const runs30d = u.runs_by_day.reduce((sum, d) => sum + d.count, 0)
    body = (
      <>
        <Grid>
          <Tile label="Analysis runs, last 30 days" value={fmt(runs30d)} />
          <Tile label="Plugin-step success rate" value={runs30d ? `${u.workflow_success_rate_pct}%` : '—'}
            note={u.success_rate_caveat ?? 'Across individual plugin steps, not whole workflows.'} />
          <Tile label="Plugins run, last 30 days" value={fmt(u.top_plugins.length)} />
        </Grid>
        {u.runs_by_day.length > 0 && (
          <Card style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Runs per day</div>
            <div style={{ height: 160 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={u.runs_by_day}>
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--muted)' }} tickLine={false} axisLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--muted)' }} tickLine={false} axisLine={false} width={28} />
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }} />
                  <Bar dataKey="count" name="Runs" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
        {u.top_plugins.length > 0 && (
          <Card style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Most-run plugins, last 30 days</div>
            {u.top_plugins.slice(0, 5).map(p => (
              <div key={p.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0', borderTop: '1px solid var(--border)' }}>
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{p.name}</span>
                <span style={{ color: 'var(--muted)' }}>{fmt(p.runs_30d)} runs</span>
              </div>
            ))}
          </Card>
        )}
      </>
    )
  }
  return <Section title="Live activity" description="Analysis runs recorded by the platform over the last 30 days.">{body}</Section>
}

function AiSection({ summary }: { summary: Load<PublicAiAndWorkflow> }) {
  let body: ReactNode
  if (summary.state === 'loading') body = <Loading />
  else if (summary.state === 'error') body = <Unavailable what="AI platform data" />
  else {
    const ai = summary.data.ai_platform
    const wf = summary.data.workflow
    body = (
      <Grid>
        <Tile label="Registered models" value={fmt(ai?.registered_models)} />
        <Tile label="Active models" value={fmt(ai?.active_models)} />
        <Tile label="Embedding models" value={fmt(ai?.embedding_models)} />
        <Tile label="LLM providers" value={fmt(ai?.llm_providers)} />
        <Tile label="Workflow bundles installed" value={fmt(wf?.workflow_bundles)} />
      </Grid>
    )
  }
  return <Section title="AI platform" description="Live counts from the model registry and workflow-bundle services.">{body}</Section>
}

const INDEX_LABELS: Record<string, string> = { star: 'STAR', bwa: 'BWA', bowtie2: 'Bowtie2', salmon: 'Salmon', cellranger: 'CellRanger' }

function GenomesSection({ reference }: { reference: Load<ReferenceStatus> }) {
  let body: ReactNode
  if (reference.state === 'loading') body = <Loading />
  else if (reference.state === 'error' || !reference.data.available) body = <Unavailable what="Reference data status" />
  else if (reference.data.organisms.length === 0) body = <Card><span style={{ fontSize: 13, color: 'var(--muted)' }}>No reference genomes installed yet.</span></Card>
  else body = (
    <Card padding={0}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: 'left', color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            <th style={{ padding: '10px 14px' }}>Organism</th>
            <th style={{ padding: '10px 14px' }}>Assembly</th>
            <th style={{ padding: '10px 14px' }}>Prepared indexes</th>
          </tr>
        </thead>
        <tbody>
          {reference.data.organisms.map(o => (
            <tr key={`${o.organism}/${o.assembly}`} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '8px 14px', color: 'var(--text)', textTransform: 'capitalize' }}>{o.organism}</td>
              <td style={{ padding: '8px 14px', fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{o.assembly}</td>
              <td style={{ padding: '6px 14px' }}>
                {Object.entries(o.indexes).map(([idx, ok]) => <Badge key={idx} ok={ok}>{INDEX_LABELS[idx] ?? idx}</Badge>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
  return <Section title="Reference genomes" description="Checked live on disk: green means the index is prepared and ready to use.">{body}</Section>
}

function BackendsSection({ backends }: { backends: Load<BackendStatus> }) {
  let body: ReactNode
  if (backends.state === 'loading') body = <Loading />
  else if (backends.state === 'error') body = <Unavailable what="Execution backend status" />
  else body = (
    <Card>
      {Object.entries(backends.data).map(([key, b]) => (
        <Badge key={key} ok={b.configured}>{b.label}{b.configured ? ' · configured' : ' · not configured'}</Badge>
      ))}
    </Card>
  )
  return <Section title="Execution backends" description="Where workflows can run in this deployment.">{body}</Section>
}

function CodebaseSection({ stats }: { stats: Load<PublicStats> }) {
  let body: ReactNode
  if (stats.state === 'loading') body = <Loading />
  else if (stats.state === 'error' || stats.data.total_lines === null) body = <Unavailable what="Codebase statistics" />
  else body = (
    <Grid>
      <Tile label="Lines of code" value={fmt(stats.data.total_lines)} />
      <Tile label="Source files" value={fmt(stats.data.total_files)} />
      <Tile label="Repositories measured" value={fmt(stats.data.repos_measured)} />
    </Grid>
  )
  return <Section title="Codebase" description="From the latest ecosystem report scan.">{body}</Section>
}

const SEVERITY_COLOR: Record<string, string> = { high: 'var(--red)', medium: 'var(--amber)', low: 'var(--muted)' }

function IssuesSection({ issues }: { issues: Load<PublicIssue[]> }) {
  let body: ReactNode
  if (issues.state === 'loading') body = <Loading />
  else if (issues.state === 'error') body = <Unavailable what="The known-issues list" />
  else if (issues.data.length === 0) body = <Card><span style={{ fontSize: 13, color: 'var(--green)' }}>No open known issues.</span></Card>
  else body = (
    <Card padding={0}>
      {issues.data.map((i, n) => (
        <div key={i.id} style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', alignItems: 'baseline', padding: '10px 14px', borderTop: n ? '1px solid var(--border)' : 'none' }}>
          <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: SEVERITY_COLOR[i.severity] ?? 'var(--muted)' }}>{i.severity}</span>
          <span style={{ fontSize: 13, color: 'var(--text)', flex: 1, minWidth: 200 }}>{i.title}</span>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {[i.area, i.status, i.opened_at && `opened ${new Date(i.opened_at).toLocaleDateString()}`].filter(Boolean).join(' · ')}
          </span>
        </div>
      ))}
    </Card>
  )
  return <Section title="Known issues" description="Problems we are aware of and working on.">{body}</Section>
}

export default function PublicOverviewPage({ refreshKey }: { refreshKey: number }) {
  const stats = useLoad(fetchPublicStats, refreshKey)
  const usage = useLoad(fetchUsage, refreshKey)
  const summary = useLoad(fetchAiAndWorkflow, refreshKey)
  const reference = useLoad(fetchReferenceStatus, refreshKey)
  const backends = useLoad(fetchBackends, refreshKey)
  const issues = useLoad(fetchOpenIssues, refreshKey)
  const uptime = useLoad(fetchUptime, refreshKey)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>OmniBioAI Platform Overview</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Live, read-only view of the platform. Every figure says where it comes from.
        </p>
      </div>
      <StatusStrip refreshKey={refreshKey} stats={stats} />
      <UptimeSection uptime={uptime} />
      <CatalogSection />
      <ActivitySection usage={usage} />
      <AiSection summary={summary} />
      <GenomesSection reference={reference} />
      <BackendsSection backends={backends} />
      <CodebaseSection stats={stats} />
      <IssuesSection issues={issues} />
    </div>
  )
}
