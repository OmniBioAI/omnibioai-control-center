import { useEffect, useState } from 'react'
import { Info, ShieldAlert } from 'lucide-react'
import {
  fetchWorkflows, fetchCategories, fetchRuns,
  type WorkflowRow, type CategoryStat, type WorkflowRun,
} from '../../workflows'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState } from '../../components/ui'

// PR A3 (Admin Console Capability Parity -- Workflows). Flat page, no
// organization picker -- workflow definitions/categories aren't
// org-owned (global bundles, workflow.read-gated only), and GET /v1/runs
// has no organization filtering upstream at all (see below), so there
// is nothing to pick an org *for* on this page.
//
// Three tabs, all built from real endpoints only (no invented data):
//   - Workflows: GET /v1/workflows (workflow.read)
//   - Categories: GET /v1/categories (workflow.read)
//   - Runs: GET /v1/runs (workflow.execute) -- see the Runs tab's own
//     banner and RunsNotice component below for the multi-tenancy
//     caveat this endpoint carries upstream.
//
// Read-only: no run submission, no workflow enable/disable toggle, no
// registration in this first PR (all three are write actions gated by
// separate permissions -- workflow.execute/workflow.manage/
// workflow.publish -- out of this PR's read-only scope).

type Tab = 'workflows' | 'categories' | 'runs'

function formatDate(iso?: string): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// classify() mirrors ToolExecutionPage.tsx's own convention: distinguish
// "no permission" from a genuine error, by the thrown message's
// trailing status suffix.
function classify(message: string): 'denied' | 'error' {
  return message.endsWith(' 401') || message.endsWith(' 403') ? 'denied' : 'error'
}

function DeniedState({ permission }: { permission: string }) {
  return (
    <EmptyState
      icon={ShieldAlert}
      title="Permission denied"
      description={`You don't have ${permission}, so this can't be shown here. This is enforced by omnibioai-workflow-bundles, not this page.`}
    />
  )
}

// IMPORTANT: this notice exists because GET /v1/runs genuinely has no
// organization-level filtering upstream today -- not a caveat this page
// is choosing to add for effect. Its own source states plainly that
// organization_id on each run is "logging/audit context only -- not an
// access-control boundary" and that isolation is a tracked upstream
// follow-up (see routes_workflow_bundles_proxy.py's module comment for
// the exact citation). This page does not filter, group, or otherwise
// narrow the response by organization_id -- doing so here would
// misrepresent a boundary that does not actually exist server-side,
// and would itself be exactly the kind of control-center-side
// authorization logic this PR is forbidden from adding.
function RunsNotice() {
  return (
    <div style={{
      display: 'flex', gap: 10, alignItems: 'flex-start', padding: '12px 14px', marginBottom: 16,
      background: 'rgba(217, 119, 6, 0.08)', border: '1px solid var(--amber)', borderRadius: 8,
    }}>
      <Info size={16} color="var(--amber)" style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.5 }}>
        Workflow run visibility is currently provided by the upstream workflow service. The
        current workflow-bundles API does not yet enforce organization-level filtering for run
        history. Organization isolation for workflow runs is tracked as an upstream multi-tenant
        improvement. This is not an Admin Console bug and not an IAM bypass introduced by this
        page -- it is an existing upstream service limitation, surfaced here rather than hidden.
      </div>
    </div>
  )
}

type WorkflowsState =
  | { status: 'loading' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: WorkflowRow[] }

function WorkflowsTab() {
  const [state, setState] = useState<WorkflowsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchWorkflows()
      .then(rows => setState({ status: 'ready', rows }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', reason: message } : { status: 'error', message })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading workflows…" />
  if (state.status === 'denied') return <DeniedState permission="workflow.read" />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { rows } = state
  const enabled = rows.filter(r => r.enabled).length

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="Registered Workflows" value={rows.length} />
        <StatCard label="Enabled" value={enabled} />
        <StatCard label="Disabled" value={rows.length - enabled} />
      </div>
      <DataTable
        rowKey={r => r.id}
        emptyLabel="No workflows registered yet."
        rows={rows}
        columns={[
          { key: 'name', header: 'Name', render: r => r.display_name },
          { key: 'category', header: 'Category', render: r => r.category },
          { key: 'engine', header: 'Engine', render: r => r.engine },
          { key: 'version', header: 'Version', render: r => <code style={{ fontSize: 11 }}>{r.version}</code> },
          { key: 'enabled', header: 'Enabled', render: r => r.enabled ? 'Yes' : 'No' },
          { key: 'created', header: 'Created', render: r => formatDate(r.created_at ?? undefined) },
        ]}
      />
    </>
  )
}

type CategoriesState =
  | { status: 'loading' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: CategoryStat[] }

function CategoriesTab() {
  const [state, setState] = useState<CategoriesState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchCategories()
      .then(rows => setState({ status: 'ready', rows }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', reason: message } : { status: 'error', message })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading categories…" />
  if (state.status === 'denied') return <DeniedState permission="workflow.read" />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  return (
    <DataTable
      rowKey={c => c.category}
      emptyLabel="No workflow categories yet."
      rows={state.rows}
      columns={[
        { key: 'category', header: 'Category', render: c => c.category },
        { key: 'count', header: 'Total Workflows', render: c => c.count },
        { key: 'enabled_count', header: 'Enabled', render: c => c.enabled_count },
      ]}
    />
  )
}

type RunsState =
  | { status: 'loading' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; runs: WorkflowRun[] }

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
  if (state.status === 'denied') return <><RunsNotice /><DeniedState permission="workflow.execute" /></>
  if (state.status === 'error') return <><RunsNotice /><ErrorState message={state.message} onRetry={load} /></>

  return (
    <>
      <RunsNotice />
      <DataTable
        rowKey={r => r.run_id}
        emptyLabel="No workflow runs recorded yet."
        rows={state.runs}
        columns={[
          { key: 'run_id', header: 'Run ID', render: r => <code style={{ fontSize: 11 }}>{r.run_id}</code> },
          { key: 'workflow', header: 'Workflow', render: r => r.workflow_name ?? (r.workflow_id != null ? `#${r.workflow_id}` : '—') },
          { key: 'status', header: 'Status', render: r => r.status },
          { key: 'engine', header: 'Engine', render: r => r.engine ?? '—' },
          { key: 'requested_by', header: 'Requested By', render: r => r.requested_by ?? '—' },
          { key: 'organization_id', header: 'Organization', render: r => r.organization_id != null ? `Org #${r.organization_id}` : '—' },
          { key: 'started', header: 'Started', render: r => formatDate(r.started_at) },
        ]}
      />
    </>
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

export default function WorkflowsPage() {
  const [tab, setTab] = useState<Tab>('workflows')

  return (
    <div>
      <SectionHeader
        title="Workflows"
        description="Registered bioinformatics workflow bundles and their run history, served by omnibioai-workflow-bundles."
      />
      <Card style={{ marginBottom: 16, padding: '0 16px' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'workflows'} onClick={() => setTab('workflows')}>Workflows</TabButton>
          <TabButton active={tab === 'categories'} onClick={() => setTab('categories')}>Categories</TabButton>
          <TabButton active={tab === 'runs'} onClick={() => setTab('runs')}>Runs</TabButton>
        </div>
      </Card>
      {tab === 'workflows' && <WorkflowsTab />}
      {tab === 'categories' && <CategoriesTab />}
      {tab === 'runs' && <RunsTab />}
    </div>
  )
}
