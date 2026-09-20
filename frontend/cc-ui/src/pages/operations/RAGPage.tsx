import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import {
  fetchStudies, fetchCacheStats, fetchRagHealth, RagRequestError,
  type StudySummary, type CacheStats, type RagHealth,
} from '../../rag'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState } from '../../components/ui'

// PR A4 (Admin Console Capability Parity -- RAG/PubMed). Flat page, no
// organization picker. Every request carries the viewing admin's own IAM
// token (see rag.ts's module comment): omnibioai-rag decides access itself
// -- dataset.read for the collection data (tenant-filtered to what the
// caller's organization may see), manage_all_orgs for query-cache stats --
// so a caller who can open this page can still be refused by RAG. What is
// shown for a refusal is driven by the HTTP status (RagRequestError.status),
// never by the backend's error wording.
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
//     manage_all_orgs-gated by RAG) -- the only two endpoints RAG exposes about
//     its own operational state; there is no query-latency or
//     retrieval-accuracy metric anywhere in this service's API to show
//     here.

type Tab = 'knowledge-base' | 'pubmed' | 'status'

type Failure = 'unauthenticated' | 'forbidden' | 'error'

function classify(error: unknown): Failure {
  if (error instanceof RagRequestError) {
    if (error.status === 401) return 'unauthenticated'
    if (error.status === 403) return 'forbidden'
  }
  return 'error'
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

// 403: RAG refused this caller. The message names what RAG requires rather
// than blaming a credential -- the caller's own permissions are the issue.
function ForbiddenState({ requires }: { requires: string }) {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Insufficient permissions"
      description={`Your account is not permitted to view this RAG data. The RAG service requires ${requires} for it and decides access itself; your Admin Console session is unaffected.`}
    />
  )
}

// 401 relayed from RAG: the Admin Console accepted the session, RAG did
// not accept the forwarded token. The console session is left intact (see
// rag.ts), so say so instead of implying the user was signed out.
function UnauthenticatedState() {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="RAG did not accept your session"
      description="The RAG service rejected your sign-in token for this request. Your Admin Console session is still active. If this persists, sign out and back in."
    />
  )
}

const STUDIES_REQUIRES = 'the dataset.read permission'
const CACHE_STATS_REQUIRES = 'platform-admin access (manage_all_orgs)'

type StudiesState =
  | { status: 'loading' }
  | { status: 'unauthenticated'; message: string }
  | { status: 'forbidden'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; studies: StudySummary[] }

function useStudies() {
  const [state, setState] = useState<StudiesState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchStudies()
      .then(r => setState({ status: 'ready', studies: r.studies }))
      .catch((e: unknown) => setState({ status: classify(e), message: errorMessage(e) } as StudiesState))
  }

  useEffect(load, [])
  return { state, load }
}

function KnowledgeBaseTab() {
  const { state, load } = useStudies()

  if (state.status === 'loading') return <LoadingState label="Loading knowledge base…" />
  if (state.status === 'forbidden') return <ForbiddenState requires={STUDIES_REQUIRES} />
  if (state.status === 'unauthenticated') return <UnauthenticatedState />
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
  if (state.status === 'forbidden') return <ForbiddenState requires={STUDIES_REQUIRES} />
  if (state.status === 'unauthenticated') return <UnauthenticatedState />
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
  | { status: 'error'; message: string }
  | { status: 'ready'; health: RagHealth; cache: CacheStats | null; cacheIssue: Failure | null }

function CacheUnavailable({ issue }: { issue: Failure }) {
  const text =
    issue === 'forbidden'
      ? `Not available -- query-cache statistics require ${CACHE_STATS_REQUIRES}, which your account does not have. Service health above is unaffected.`
      : issue === 'unauthenticated'
        ? "Not available -- the RAG service did not accept your sign-in token for cache statistics. Your Admin Console session is still active; service health above is unaffected."
        : "Not available -- the cache-stats endpoint didn't respond. Service health above is unaffected."
  return <div style={{ fontSize: 12, color: 'var(--muted)' }}>{text}</div>
}

function QueryServiceStatusTab() {
  const [state, setState] = useState<StatusState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    // /rag/health has no auth requirement upstream, so a failure there is a
    // plain service error. /rag/cache-stats is gated by RAG itself
    // (manage_all_orgs) and may fail independently -- refused for this
    // caller, say -- without that being a reason to hide health entirely:
    // health is awaited directly, cache stats degrades to an explained
    // "not available" on its own failure rather than failing the whole tab.
    Promise.allSettled([fetchRagHealth(), fetchCacheStats()])
      .then(([healthResult, cacheResult]) => {
        if (healthResult.status === 'rejected') {
          setState({ status: 'error', message: errorMessage(healthResult.reason) })
          return
        }
        setState({
          status: 'ready',
          health: healthResult.value,
          cache: cacheResult.status === 'fulfilled' ? cacheResult.value : null,
          cacheIssue: cacheResult.status === 'rejected' ? classify(cacheResult.reason) : null,
        })
      })
  }

  useEffect(load, [])

  if (state.status === 'loading') return <LoadingState label="Loading service status…" />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { health, cache, cacheIssue } = state
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
          <CacheUnavailable issue={cacheIssue ?? 'error'} />
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
