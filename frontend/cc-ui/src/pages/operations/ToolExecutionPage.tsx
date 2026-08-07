import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchRuns, fetchTools, fetchToolCapabilities,
  type RunRecord, type ToolSummary,
} from '../../tes'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState } from '../../components/ui'

// PR A1 (Admin Console Capability Parity -- Tool Execution). Flat page,
// no organization picker: omnibioai-tes's GET /api/runs self-scopes to
// the caller's own organization_id server-side (see tes.ts's module
// comment) -- there is no "view another org's runs" endpoint for an
// admin to pick a different organization the way Billing/IAM do, so
// this page follows AuditLogsPage.tsx's flat shape instead of
// BillingPage.tsx's org-picker shape.
//
// Two tabs: Runs (permission-gated by TES's own require_permission(
// WORKFLOW_EXECUTE), classified via the ' 403'/' 404' suffix convention
// every other proxied page in this app already uses) and Tools
// (unauthenticated upstream -- always visible once the page itself is
// reachable, no separate denied state needed for that half).
//
// Read-only: no run submission/cancellation in this first PR (see
// tes.ts's module comment for why).

type Tab = 'runs' | 'tools'

const RUN_STATE_COLOR: Record<string, string> = {
  QUEUED: 'var(--muted)',
  RUNNING: 'var(--accent)',
  SUCCEEDED: 'var(--color-success)',
  FAILED: 'var(--red)',
  CANCELLED: 'var(--muted)',
}

function RunStateBadge({ state }: { state: string }) {
  const color = RUN_STATE_COLOR[state] ?? 'var(--muted)'
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
      background: 'rgba(255,255,255,0.08)', color, whiteSpace: 'nowrap',
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {state}
    </span>
  )
}

function formatDate(iso?: string): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// classify() mirrors BillingPage.tsx/AuditLogsPage.tsx's own convention:
// distinguish "no permission" (403) from a genuine error, by the
// thrown message's trailing status suffix -- no authorization decision
// is made here, this only decides how to render what the backend
// already decided.
function classify(message: string): 'denied' | 'error' {
  return message.endsWith(' 403') || message.endsWith(' 401') ? 'denied' : 'error'
}

type RunsState =
  | { status: 'loading' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; runs: RunRecord[] }

function RunsTab() {
  const [state, setState] = useState<RunsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchRuns()
      .then(runs => setState({ status: 'ready', runs }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', reason: message } : { status: 'error', message })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading runs…" />
  if (state.status === 'denied') {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Permission denied"
        description="You don't have workflow.execute, so runs can't be shown here. This is enforced by omnibioai-tes, not this page."
      />
    )
  }
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { runs } = state
  const running = runs.filter(r => r.state === 'RUNNING').length
  const queued = runs.filter(r => r.state === 'QUEUED').length
  const failed = runs.filter(r => r.state === 'FAILED').length

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="Total Runs" value={runs.length} />
        <StatCard label="Running" value={running} />
        <StatCard label="Queued" value={queued} />
        <StatCard label="Failed" value={failed} />
      </div>
      <DataTable
        rowKey={r => r.run_id}
        emptyLabel="No runs for your organization yet."
        rows={runs}
        columns={[
          { key: 'run_id', header: 'Run ID', render: r => <code style={{ fontSize: 11 }}>{r.run_id}</code> },
          { key: 'tool', header: 'Tool', render: r => r.tool_id },
          { key: 'state', header: 'State', render: r => <RunStateBadge state={r.state} /> },
          { key: 'server', header: 'Server', render: r => r.server_id },
          { key: 'created', header: 'Created', render: r => formatDate(r.created_at) },
        ]}
      />
    </>
  )
}

type ToolsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; tools: ToolSummary[]; capabilities: Map<string, string[]> }

function ToolsTab() {
  const [state, setState] = useState<ToolsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    Promise.all([fetchTools(), fetchToolCapabilities()])
      .then(([tools, capabilities]) => {
        const capMap = new Map(capabilities.map(c => [c.tool_id, c.backends]))
        setState({ status: 'ready', tools, capabilities: capMap })
      })
      .catch((e: unknown) => setState({ status: 'error', message: e instanceof Error ? e.message : String(e) }))
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading tools…" />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { tools, capabilities } = state
  return (
    <DataTable
      rowKey={t => t.tool_id}
      emptyLabel="No tools registered."
      rows={tools}
      columns={[
        { key: 'tool_id', header: 'Tool ID', render: t => <code style={{ fontSize: 11 }}>{t.tool_id}</code> },
        { key: 'name', header: 'Name', render: t => t.name ?? '—' },
        { key: 'backends', header: 'Backends', render: t => (capabilities.get(t.tool_id) ?? []).join(', ') || '—' },
      ]}
    />
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      style={{
        fontSize: 13, fontWeight: 600, padding: '8px 4px', marginRight: 20,
        background: 'none', border: 'none', borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
        color: active ? 'var(--text)' : 'var(--text2)', cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export default function ToolExecutionPage() {
  const [tab, setTab] = useState<Tab>('runs')

  return (
    <div>
      <SectionHeader
        title="Tool Execution"
        description="Bioinformatics tool runs and the tool registry, served by omnibioai-tes. Runs shown are scoped to your own organization."
      />
      <Card style={{ marginBottom: 16, padding: '0 16px' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'runs'} onClick={() => setTab('runs')}>Runs</TabButton>
          <TabButton active={tab === 'tools'} onClick={() => setTab('tools')}>Tools</TabButton>
        </div>
      </Card>
      {tab === 'runs' ? <RunsTab /> : <ToolsTab />}
    </div>
  )
}
