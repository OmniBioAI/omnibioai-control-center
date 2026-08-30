import { useEffect, useState } from 'react'
import { Info, ShieldAlert, Workflow } from 'lucide-react'
import {
  fetchAgentGraphs, classifyArchitecture, ARCHITECTURE_LABEL,
  type AgentGraph, type ArchitectureKind,
} from '../../agent_orchestrator'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState, SessionExpiredState, BackLink } from '../../components/ui'
import { classifyAuthError } from '../../format'

// Agentic AI nav item (feature/agentic-ai-navbar). Flat page, no
// organization picker -- agent_orchestrator's graph catalog isn't
// org-owned (confirmed by reading its schema directly, same as
// tool-execution/ai-models/workflows/rag above it in this nav section).
//
// Built from exactly one real endpoint (GET /agent-orchestrator/graphs,
// proxying GET /api/agent/graphs/ -- see agent_orchestrator.ts's own
// module comment for the upstream field shapes and the two disclosed
// limitations this page works around rather than hides:
//   1. The endpoint only ever returns enabled graphs (no way to ask for
//      disabled ones) -- so "Enabled" is not shown as a per-row toggle
//      state, it's stated once, plainly, in InfoBanner below.
//   2. There is no list-all-runs endpoint anywhere in agent_orchestrator
//      -- only POST ops/agent/run/ to start one and GET .../status by
//      run_id once you already have one. Recent Runs in the drill-in
//      below is therefore a real EmptyState, not an invented row.
//
// Per this PR's own hard rule (no fabricated data): every name,
// description, version, and DAG node/edge on this page is copied
// verbatim from that one real response. The only thing this file adds is
// classifyArchitecture()'s display-only grouping (agent_orchestrator.ts's
// own comment explains why there's no upstream field for this) -- no
// invented agent, no invented timestamp, no invented health status.

const ARCHITECTURE_ORDER: ArchitectureKind[] = ['fixed_pipeline', 'react_agent', 'composite']

function InfoBanner() {
  return (
    <div style={{
      display: 'flex', gap: 10, alignItems: 'flex-start', padding: '12px 14px', marginBottom: 16,
      background: 'rgba(217, 119, 6, 0.08)', border: '1px solid var(--amber)', borderRadius: 8,
    }}>
      <Info size={16} color="var(--amber)" style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.5 }}>
        This catalog is read from omnibioai-workbench's live agent graph registry
        (GET /api/agent/graphs/). Two real limitations of that endpoint, surfaced here rather than
        hidden: it only ever returns <em>enabled</em> graphs (a disabled graph is simply absent, not
        returned with a disabled flag), and agent_orchestrator has no list-all-runs endpoint today --
        only a per-run status lookup once a run already exists. Run health and recent-run history are
        not yet wired into this page; see "Recent Runs" on a graph's detail view.
      </div>
    </div>
  )
}

function DeniedState() {
  return (
    <EmptyState
      icon={ShieldAlert}
      title="Permission denied"
      description="omnibioai-workbench rejected this request. This is enforced by that service, not this page."
    />
  )
}

type GraphsState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'denied'; reason: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; graphs: AgentGraph[] }

function useAgentGraphs() {
  const [state, setState] = useState<GraphsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchAgentGraphs()
      .then(graphs => setState({ status: 'ready', graphs }))
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

function GraphGroup({ kind, graphs, onSelect }: { kind: ArchitectureKind; graphs: AgentGraph[]; onSelect: (graphId: string) => void }) {
  if (graphs.length === 0) return null
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>
        {ARCHITECTURE_LABEL[kind]} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>({graphs.length})</span>
      </div>
      <DataTable
        rowKey={g => g.graph_id}
        emptyLabel="No graphs in this group."
        rows={graphs}
        columns={[
          { key: 'name', header: 'Name', render: g => (
            <button
              onClick={() => onSelect(g.graph_id)}
              style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', fontWeight: 600, fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            >
              {g.display_name}
            </button>
          ) },
          { key: 'graph_id', header: 'Graph ID', render: g => <code style={{ fontSize: 11 }}>{g.graph_id}</code> },
          { key: 'version', header: 'Version', render: g => <code style={{ fontSize: 11 }}>{g.version}</code> },
          { key: 'nodes', header: 'DAG Nodes', render: g => g.dag?.nodes?.length ?? '—' },
        ]}
      />
    </Card>
  )
}

function DagView({ dag }: { dag: AgentGraph['dag'] }) {
  if (!dag || dag.nodes.length === 0) {
    return <EmptyState title="No DAG metadata" description="This graph's definition doesn't include dag.nodes/edges." />
  }
  const labelFor = (id: string) => dag.nodes.find(n => n.id === id)?.label ?? id
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text2)' }}>Nodes ({dag.nodes.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {dag.nodes.map(n => (
            <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
              <span style={{ flex: 1 }}>{n.label ?? n.id}</span>
              {n.kind && <span style={{ fontSize: 10, color: 'var(--muted)', background: 'var(--bg3)', borderRadius: 99, padding: '2px 8px', whiteSpace: 'nowrap' }}>{n.kind}</span>}
              {n.plugin && <code style={{ fontSize: 10, color: 'var(--muted)' }}>{n.plugin}</code>}
            </div>
          ))}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: 'var(--text2)' }}>Edges ({dag.edges.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {dag.edges.map((e, i) => (
            <div key={`${e.from}->${e.to}-${i}`} style={{ fontSize: 12, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
              {labelFor(e.from)} <span style={{ color: 'var(--muted)' }}>→</span> {labelFor(e.to)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function RecentRunsNotice() {
  return (
    <EmptyState
      icon={Workflow}
      title="Not yet connected to live run data"
      description="agent_orchestrator has no list-all-runs endpoint today (only POST ops/agent/run/ to start a run and GET .../status/{run_id} once you already have one). Wiring per-graph run history here is a tracked follow-up, not something this page invents in the meantime."
    />
  )
}

function GraphDetail({ graph, onBack }: { graph: AgentGraph; onBack: () => void }) {
  return (
    <>
      <BackLink label="Back to Agentic AI" onBack={onBack} />
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{graph.display_name}</div>
            <code style={{ fontSize: 11, color: 'var(--muted)' }}>{graph.graph_id}</code>
          </div>
          <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--muted)', background: 'var(--bg3)', borderRadius: 99, padding: '3px 9px' }}>
            {ARCHITECTURE_LABEL[classifyArchitecture(graph)]}
          </span>
        </div>
        {graph.description && <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 4 }}>{graph.description}</div>}
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Version <code>{graph.version}</code></div>
      </Card>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>DAG</div>
        <DagView dag={graph.dag} />
      </Card>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Recent Runs</div>
        <RecentRunsNotice />
      </Card>
    </>
  )
}

export default function AgenticAIPage() {
  const { state, load } = useAgentGraphs()
  const [selectedGraphId, setSelectedGraphId] = useState<string | null>(null)

  if (state.status === 'loading') return <LoadingState label="Loading agent graphs…" />
  if (state.status === 'session') return <SessionExpiredState />
  if (state.status === 'denied') return <DeniedState />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { graphs } = state
  const selected = selectedGraphId != null ? graphs.find(g => g.graph_id === selectedGraphId) ?? null : null

  const grouped = new Map<ArchitectureKind, AgentGraph[]>()
  for (const g of graphs) {
    const kind = classifyArchitecture(g)
    const list = grouped.get(kind) ?? []
    list.push(g)
    grouped.set(kind, list)
  }
  const counts: Record<ArchitectureKind, number> = {
    fixed_pipeline: grouped.get('fixed_pipeline')?.length ?? 0,
    react_agent: grouped.get('react_agent')?.length ?? 0,
    composite: grouped.get('composite')?.length ?? 0,
  }

  return (
    <div>
      <SectionHeader
        title="Agentic AI"
        description="Agent graph catalog, served live by omnibioai-workbench's agent_orchestrator service."
      />
      <InfoBanner />
      {selected ? (
        <GraphDetail graph={selected} onBack={() => setSelectedGraphId(null)} />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
            <StatCard label="Total Agent Graphs" value={graphs.length} />
            <StatCard label="Fixed Pipelines" value={counts.fixed_pipeline} />
            <StatCard label="ReAct Agents" value={counts.react_agent} />
            <StatCard label="Composite Agents" value={counts.composite} />
          </div>
          {graphs.length === 0
            ? <EmptyState title="No agent graphs returned" description="omnibioai-workbench's catalog is currently empty (or every graph is disabled)." />
            : ARCHITECTURE_ORDER.map(kind => (
              <GraphGroup key={kind} kind={kind} graphs={grouped.get(kind) ?? []} onSelect={setSelectedGraphId} />
            ))}
        </>
      )}
    </div>
  )
}
