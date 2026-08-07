import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchModels, fetchModelRegistryHealth, fetchModelRegistryAuthStatus,
  type ModelVersionRow, type ModelRegistryHealth, type ModelRegistryAuthStatus,
} from '../../model_registry'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState, SessionExpiredState } from '../../components/ui'
import { formatDate, classifyAuthError } from '../../format'

// PR A2 (Admin Console Capability Parity -- AI Models). Flat page, no
// organization picker: model-registry has no organization concept
// anywhere in its schema (confirmed by reading its own source), same
// reasoning routes_dashboard.py's own _ai_platform_section() comment
// already documents.
//
// Three tabs, all built from real endpoints only (no invented data):
//   - Registered Models: GET /v1/models grouped client-side by
//     (task, model_name) -- model-registry has no separate "distinct
//     models" endpoint, this is a display-only grouping of the same
//     rows Model Versions shows flat.
//   - Model Versions: the same GET /v1/models response, one row per
//     version, unmodified.
//   - Runtime Status: GET /health + GET /v1/auth/status -- the only two
//     endpoints this service exposes about its own operational state;
//     there is no serving/compute runtime here to report on (this is a
//     metadata/artifact registry, not a model server), so this tab is
//     honestly "is the registry up and how is it configured to
//     authenticate," not invented infrastructure metrics.
//
// Permission/error handling is included defensively (EmptyState+
// ShieldAlert on a 403, a distinct SessionExpiredState on a 401) even
// though none of these three routes are gated upstream today -- see
// model_registry.ts's module comment. If that ever changes, this page
// already renders it correctly without a follow-up UI change. PR E2:
// previously a local classify() folded 401 into the same "Permission
// denied" bucket as 403 -- now uses the shared classifyAuthError, same
// fix as every other page in this app that had the same conflation.

type Tab = 'registered' | 'versions' | 'runtime'

const STAGE_COLOR: Record<string, string> = {
  production: 'var(--color-success)',
  staging: 'var(--accent)',
  archived: 'var(--muted)',
  none: 'var(--muted)',
}

function StageBadge({ stage }: { stage?: string }) {
  const label = stage ?? 'none'
  const color = STAGE_COLOR[label] ?? 'var(--muted)'
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
      background: 'rgba(255,255,255,0.08)', color, whiteSpace: 'nowrap',
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {label}
    </span>
  )
}

interface ModelGroup {
  task: string
  model_name: string
  versionCount: number
  stages: string[]
  latestVersion: string
  latestCreatedAt?: string
}

// Display-only grouping (task, model_name) -> versions -- not a
// registration/promotion decision, no business logic duplicated from
// model-registry itself. "Latest" is by created_at when present,
// falling back to array order (model-registry doesn't guarantee
// created_at on every row -- arbitrary metadata could omit it).
function groupByModel(rows: ModelVersionRow[]): ModelGroup[] {
  const groups = new Map<string, ModelVersionRow[]>()
  for (const row of rows) {
    const key = `${row.task}::${row.model_name}`
    const list = groups.get(key) ?? []
    list.push(row)
    groups.set(key, list)
  }
  return Array.from(groups.entries()).map(([key, versions]) => {
    const [task, model_name] = key.split('::')
    const sorted = [...versions].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    return {
      task,
      model_name,
      versionCount: versions.length,
      stages: Array.from(new Set(versions.map(v => v.stage).filter((s): s is string => !!s))),
      latestVersion: sorted[0]?.version ?? '—',
      latestCreatedAt: sorted[0]?.created_at,
    }
  })
}

type ModelsState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: ModelVersionRow[] }

function useModels() {
  const [state, setState] = useState<ModelsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchModels()
      .then(rows => setState({ status: 'ready', rows }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setState({ status: 'session' })
        else if (kind === 'denied') setState({ status: 'denied', reason: message })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [])
  return { state, load }
}

function DeniedState() {
  return (
    <EmptyState
      icon={ShieldAlert}
      title="Permission denied"
      description="omnibioai-model-registry rejected this request. This is enforced by that service, not this page."
    />
  )
}

function RegisteredModelsTab() {
  const { state, load } = useModels()

  if (state.status === 'loading') return <LoadingState label="Loading registered models…" />
  if (state.status === 'session') return <SessionExpiredState />
  if (state.status === 'denied') return <DeniedState />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const groups = groupByModel(state.rows)
  const active = groups.filter(g => g.stages.includes('staging') || g.stages.includes('production')).length

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="Registered Models" value={groups.length} />
        <StatCard label="Active (staging/production)" value={active} />
        <StatCard label="Total Versions" value={state.rows.length} />
      </div>
      <DataTable
        rowKey={g => `${g.task}::${g.model_name}`}
        emptyLabel="No models registered yet."
        rows={groups}
        columns={[
          { key: 'task', header: 'Task', render: g => g.task },
          { key: 'model_name', header: 'Model Name', render: g => g.model_name },
          { key: 'versions', header: 'Versions', render: g => g.versionCount },
          { key: 'latest', header: 'Latest Version', render: g => <code style={{ fontSize: 11 }}>{g.latestVersion}</code> },
          { key: 'stages', header: 'Stages', render: g => g.stages.length ? g.stages.map(s => <StageBadge key={s} stage={s} />) : <StageBadge stage="none" /> },
        ]}
      />
    </>
  )
}

function ModelVersionsTab() {
  const { state, load } = useModels()

  if (state.status === 'loading') return <LoadingState label="Loading model versions…" />
  if (state.status === 'session') return <SessionExpiredState />
  if (state.status === 'denied') return <DeniedState />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  return (
    <DataTable
      rowKey={r => `${r.task}::${r.model_name}::${r.version}`}
      emptyLabel="No model versions registered yet."
      rows={state.rows}
      columns={[
        { key: 'task', header: 'Task', render: r => r.task },
        { key: 'model_name', header: 'Model Name', render: r => r.model_name },
        { key: 'version', header: 'Version', render: r => <code style={{ fontSize: 11 }}>{r.version}</code> },
        { key: 'stage', header: 'Stage', render: r => <StageBadge stage={r.stage} /> },
        { key: 'created', header: 'Created', render: r => formatDate(r.created_at) },
      ]}
    />
  )
}

type RuntimeState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; health: ModelRegistryHealth; authStatus: ModelRegistryAuthStatus }

function RuntimeStatusTab() {
  const [state, setState] = useState<RuntimeState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    Promise.all([fetchModelRegistryHealth(), fetchModelRegistryAuthStatus()])
      .then(([health, authStatus]) => setState({ status: 'ready', health, authStatus }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setState({ status: 'session' })
        else if (kind === 'denied') setState({ status: 'denied', reason: message })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading runtime status…" />
  if (state.status === 'session') return <SessionExpiredState />
  if (state.status === 'denied') return <DeniedState />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { health, authStatus } = state
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Service Health</div>
        <Field title="Status">{health.ok ? 'Healthy' : 'Unhealthy'}</Field>
        <Field title="Service">{health.service}</Field>
        <Field title="Version">{health.version}</Field>
      </Card>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Authentication</div>
        <Field title="Auth Enabled">{authStatus.auth_enabled ? 'Yes' : 'No'}</Field>
        <Field title="Mode">{authStatus.mode}</Field>
        <Field title="IAM URL">{authStatus.iam_url ?? '—'}</Field>
      </Card>
    </div>
  )
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
      <span style={{ color: 'var(--text2)' }}>{title}</span>
      <span style={{ color: 'var(--text)', fontWeight: 600 }}>{children}</span>
    </div>
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

export default function AIModelsPage() {
  const [tab, setTab] = useState<Tab>('registered')

  return (
    <div>
      <SectionHeader
        title="AI Models"
        description="Registered models, versions, and registry runtime status, served by omnibioai-model-registry."
      />
      <Card style={{ marginBottom: 16, padding: '0 16px' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'registered'} onClick={() => setTab('registered')}>Registered Models</TabButton>
          <TabButton active={tab === 'versions'} onClick={() => setTab('versions')}>Model Versions</TabButton>
          <TabButton active={tab === 'runtime'} onClick={() => setTab('runtime')}>Runtime Status</TabButton>
        </div>
      </Card>
      {tab === 'registered' && <RegisteredModelsTab />}
      {tab === 'versions' && <ModelVersionsTab />}
      {tab === 'runtime' && <RuntimeStatusTab />}
    </div>
  )
}
