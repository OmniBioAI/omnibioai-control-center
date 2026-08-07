import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import {
  fetchStudies, fetchCacheStats, fetchRagHealth,
  type StudySummary, type CacheStats, type RagHealth,
} from '../../rag'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState } from '../../components/ui'

// PR A4 (Admin Console Capability Parity -- RAG/PubMed). Flat page, no
// organization picker -- the RAG corpus isn't org-owned, and the two
// endpoints this page reads (GET /v1/studies, GET /v1/cache/stats) are
// answered via a control-center-held RAGBIO_API_KEY service credential,
// not the viewing admin's own token (see rag.ts's module comment for
// the full citation). Visibility here is controlled entirely by
// control-center's own hasAdminAccess() nav gate -- this page does not
// implement, and must not be read as implementing, per-admin RAG
// authorization.
//
// Three tabs, all built from real endpoints only (no invented document
// counts, accuracy metrics, latency, embedding stats, or model info):
//   - Knowledge Base: GET /v1/studies, one row per indexed collection
//     with its real abstract_count.
//   - PubMed / Literature Index: the same GET /v1/studies response,
//     aggregated (collection count, total abstract count) -- RAG's only
//     indexed corpus today is PubMed abstracts (confirmed by reading
//     ragbio/api/server.py: list_studies() counts files under
//     ABSTRACT_FOLDER, no other corpus type exists), so this tab is an
//     honest re-framing of the same real numbers, not a second data
//     source or a fabricated one.
//   - Query Service Status: GET /health (service status/version, no
//     auth) + GET /v1/cache/stats (fuller Redis query-cache breakdown,
//     service-key gated) -- the only two endpoints RAG exposes about
//     its own operational state; there is no query-latency or
//     retrieval-accuracy metric anywhere in this service's API to show
//     here.

type Tab = 'knowledge-base' | 'pubmed' | 'status'

function classify(message: string): 'denied' | 'error' {
  return message.endsWith(' 401') || message.endsWith(' 403') ? 'denied' : 'error'
}

// Wording deliberately differs from ToolExecutionPage.tsx/WorkflowsPage.tsx's
// DeniedState: a 401/403 here means the RAGBIO_API_KEY service
// credential is missing/misconfigured on control-center's side (or RAG
// itself doesn't have one set) -- it is not a statement about the
// viewing admin's own permissions, since this page's data was never
// gated by those in the first place. See rag.ts's module comment.
function ServiceCredentialState({ message }: { message: string }) {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="RAG service credential unavailable"
      description={`omnibioai-rag rejected this request (${message}). This reflects control-center's RAGBIO_API_KEY configuration, not your own admin permissions.`}
    />
  )
}

type StudiesState =
  | { status: 'loading' }
  | { status: 'denied'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; studies: StudySummary[] }

function useStudies() {
  const [state, setState] = useState<StudiesState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchStudies()
      .then(r => setState({ status: 'ready', studies: r.studies }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', message } : { status: 'error', message })
      })
  }

  useEffect(load, [])
  return { state, load }
}

function KnowledgeBaseTab() {
  const { state, load } = useStudies()

  if (state.status === 'loading') return <LoadingState label="Loading knowledge base…" />
  if (state.status === 'denied') return <ServiceCredentialState message={state.message} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  return (
    <DataTable
      rowKey={s => s.name}
      emptyLabel="No indexed collections yet."
      rows={state.studies}
      columns={[
        { key: 'name', header: 'Collection', render: s => s.name },
        { key: 'abstract_count', header: 'Abstracts Indexed', render: s => s.abstract_count.toLocaleString() },
      ]}
    />
  )
}

function PubMedTab() {
  const { state, load } = useStudies()

  if (state.status === 'loading') return <LoadingState label="Loading literature index…" />
  if (state.status === 'denied') return <ServiceCredentialState message={state.message} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  if (state.studies.length === 0) {
    return <EmptyState title="No PubMed literature indexed yet." description="No collections exist in the knowledge base yet." />
  }

  const totalAbstracts = state.studies.reduce((sum, s) => sum + s.abstract_count, 0)

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="Collections" value={state.studies.length} />
        <StatCard label="Total Abstracts Indexed" value={totalAbstracts.toLocaleString()} />
      </div>
      <DataTable
        rowKey={s => s.name}
        emptyLabel="No PubMed literature indexed yet."
        rows={[...state.studies].sort((a, b) => b.abstract_count - a.abstract_count)}
        columns={[
          { key: 'name', header: 'Collection', render: s => s.name },
          { key: 'abstract_count', header: 'Abstracts', render: s => s.abstract_count.toLocaleString() },
        ]}
      />
    </>
  )
}

type StatusState =
  | { status: 'loading' }
  | { status: 'denied'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; health: RagHealth; cache: CacheStats | null }

function QueryServiceStatusTab() {
  const [state, setState] = useState<StatusState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    // /rag/health has no auth requirement upstream; /rag/cache-stats is
    // service-key gated and may fail independently (e.g. RAGBIO_API_KEY
    // unconfigured) without that being a reason to hide health entirely
    // -- health is awaited directly, cache stats degrades to null on
    // its own failure rather than failing the whole tab.
    Promise.allSettled([fetchRagHealth(), fetchCacheStats()])
      .then(([healthResult, cacheResult]) => {
        if (healthResult.status === 'rejected') {
          const message = healthResult.reason instanceof Error ? healthResult.reason.message : String(healthResult.reason)
          setState(classify(message) === 'denied' ? { status: 'denied', message } : { status: 'error', message })
          return
        }
        setState({
          status: 'ready',
          health: healthResult.value,
          cache: cacheResult.status === 'fulfilled' ? cacheResult.value : null,
        })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading service status…" />
  if (state.status === 'denied') return <ServiceCredentialState message={state.message} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { health, cache } = state
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Service Health</div>
        <Field title="Status">{health.status === 'ok' ? 'Healthy' : health.status}</Field>
        <Field title="Version">{health.version}</Field>
        <Field title="FAISS Version">{health.faiss_version ?? 'Not available'}</Field>
      </Card>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Query Cache</div>
        {cache ? (
          <>
            <Field title="Enabled">{cache.enabled ? 'Yes' : 'No'}</Field>
            <Field title="Connected">{cache.connected ? 'Yes' : 'No'}</Field>
            {cache.cached_queries != null && <Field title="Cached Queries">{cache.cached_queries.toLocaleString()}</Field>}
            {cache.hit_rate != null && <Field title="Hit Rate">{cache.hit_rate}%</Field>}
            {cache.hits != null && cache.misses != null && <Field title="Hits / Misses">{`${cache.hits} / ${cache.misses}`}</Field>}
          </>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Not available -- the RAGBIO_API_KEY-gated cache-stats endpoint didn't respond, service health above is unaffected.
          </div>
        )}
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

export default function RAGPage() {
  const [tab, setTab] = useState<Tab>('knowledge-base')

  return (
    <div>
      <SectionHeader
        title="RAG Knowledge System"
        description="Indexed knowledge base collections, PubMed literature coverage, and query service status, served by omnibioai-rag."
      />
      <Card style={{ marginBottom: 16, padding: '0 16px' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'knowledge-base'} onClick={() => setTab('knowledge-base')}>Knowledge Base</TabButton>
          <TabButton active={tab === 'pubmed'} onClick={() => setTab('pubmed')}>PubMed / Literature Index</TabButton>
          <TabButton active={tab === 'status'} onClick={() => setTab('status')}>Query Service Status</TabButton>
        </div>
      </Card>
      {tab === 'knowledge-base' && <KnowledgeBaseTab />}
      {tab === 'pubmed' && <PubMedTab />}
      {tab === 'status' && <QueryServiceStatusTab />}
    </div>
  )
}
