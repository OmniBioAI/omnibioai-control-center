import { useEffect, useState } from 'react'
import { ShieldAlert, Receipt, FileText } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip,
} from 'recharts'
import {
  fetchOrganizationBillingSummary, fetchInvoices, fetchInvoiceDetail, fetchCostBreakdown,
  type OrganizationBillingSummary, type InvoiceListItem, type InvoiceDetail, type CostBreakdownResult,
} from '../../billing'
import { fetchMyOrg, fetchPlatformOrgDetail } from '../../organizations'
import { hasPlatformAdminAccess } from '../../auth'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState, ActionToolbar, Button } from '../../components/ui'

// PR14.5C: billing visibility and invoice management only -- no payment
// endpoints exist on omnibioai-billing yet (deliberately out of scope,
// per this PR's own spec), so there is nothing here to "pay" an invoice
// with, only to view it.

function formatCurrency(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency.toUpperCase() }).format(amount)
  } catch {
    // An unrecognized currency code (shouldn't happen -- omnibioai-billing
    // always stores a real ISO code) falls back rather than throwing.
    return `${amount.toFixed(2)} ${currency.toUpperCase()}`
  }
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

function formatDateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// GET .../summary, .../invoices, .../cost-breakdown all 403 for a
// non-member (get_authorized_organization_id) -- .../invoices/{id} 404s
// instead (get_authorized_invoice, deliberately not distinguishing
// "doesn't exist" from "not yours"). Both render as a permission-denied
// variant here, same convention ServiceAccountsPage.tsx/SSOSettingsPage.tsx
// already established for their own proxied endpoints.
function classify(message: string): 'denied-404' | 'denied-403' | 'error' {
  if (message.endsWith(' 404')) return 'denied-404'
  if (message.endsWith(' 403')) return 'denied-403'
  return 'error'
}

const INVOICE_STATUS_COLOR: Record<string, string> = {
  DRAFT: 'var(--muted)',
  ISSUED: 'var(--blue, #0094ff)',
  PAID: 'var(--color-success, #22c55e)',
  VOID: 'var(--red)',
}

function StatusBadge({ status }: { status: string }) {
  const color = INVOICE_STATUS_COLOR[status] ?? 'var(--muted)'
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color, background: 'var(--bg2)',
      border: `1px solid ${color}`, borderRadius: 999, padding: '2px 9px',
    }}>
      {status}
    </span>
  )
}

/** Resolves a display name for the org header without inventing a new
 * endpoint -- same approach SSOSettingsPage.tsx/ServiceAccountsPage.tsx
 * already established: reuses whichever of organizations.ts's two
 * existing detail fetches the caller can actually reach. Best-effort
 * only: failure here doesn't block billing data from loading. */
function useOrgLabel(orgId: number): string {
  const [label, setLabel] = useState(`Organization #${orgId}`)
  useEffect(() => {
    let cancelled = false
    const load = hasPlatformAdminAccess() ? fetchPlatformOrgDetail(orgId) : fetchMyOrg(orgId)
    load
      .then(org => { if (!cancelled) setLabel(`${org.name} (${org.slug})`) })
      .catch(() => { /* keep the id-based fallback */ })
    return () => { cancelled = true }
  }, [orgId])
  return label
}

// ── Overview tab: current-period summary + a trailing cost-by-service
// breakdown chart, mirroring EcosystemPage.tsx's own BarChart usage. ────

const CHART_BAR_COLOR = '#0094ff'
const CHART_MUTED = '#6b7280'
const CHART_BORDER = '#2a2d3e'

function last30DayRange(): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 30)
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}

function CostBreakdownChart({ orgId }: { orgId: number }) {
  const [state, setState] = useState<{ status: 'loading' } | { status: 'error' } | { status: 'ready'; data: CostBreakdownResult }>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    const { start, end } = last30DayRange()
    fetchCostBreakdown(orgId, start, end, 'service')
      .then(data => { if (!cancelled) setState({ status: 'ready', data }) })
      .catch(() => { if (!cancelled) setState({ status: 'error' }) })
    return () => { cancelled = true }
  }, [orgId])

  if (state.status === 'loading') return <LoadingState label="Loading cost breakdown…" />
  // Best-effort chart -- a failure here (e.g. no billing plan assigned
  // yet) doesn't block the rest of the Overview tab, it just omits the
  // chart silently rather than showing a second, redundant error box.
  if (state.status === 'error') return null

  const entries = Object.entries(state.data.breakdown)
  if (entries.length === 0) {
    return <EmptyState title="No usage in the last 30 days" description="Cost breakdown will appear here once usage has been rated for this organization." />
  }

  const barData = entries
    .map(([name, v]) => ({ name, value: Number(v.cost) }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 10)

  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={barData} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_BORDER} horizontal={false} />
          <XAxis type="number" tickFormatter={v => formatCurrency(v, state.data.currency)} tick={{ fill: CHART_MUTED, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: CHART_MUTED, fontSize: 10 }} axisLine={false} tickLine={false} width={90} />
          <Tooltip
            formatter={(v: number) => formatCurrency(v, state.data.currency)}
            contentStyle={{ background: '#1a1d2e', border: `1px solid ${CHART_BORDER}`, borderRadius: 8, fontSize: 12 }}
          />
          <Bar dataKey="value" fill={CHART_BAR_COLOR} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

type LoadState<T> = { status: 'loading' } | { status: 'denied'; reason: string } | { status: 'error'; message: string } | { status: 'ready'; data: T }

function OverviewTab({ orgId }: { orgId: number }) {
  const [state, setState] = useState<LoadState<OrganizationBillingSummary>>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchOrganizationBillingSummary(orgId)
      .then(data => setState({ status: 'ready', data }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404' || kind === 'denied-403') setState({ status: 'denied', reason: "This organization's billing summary isn't accessible to you." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId])

  if (state.status === 'loading') return <LoadingState label="Loading billing summary…" />
  if (state.status === 'denied') return <EmptyState icon={ShieldAlert} title="Permission denied" description={state.reason} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { data } = state
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 20 }}>
        <StatCard label="Current period usage" value={formatCurrency(data.current_usage_cost, data.currency)} />
        <StatCard label="Outstanding balance" value={formatCurrency(data.outstanding_amount, data.currency)} accent={data.outstanding_amount > 0 ? 'amber' : 'default'} />
        <StatCard label="Invoices to date" value={data.invoice_count} />
        <StatCard
          label="Current billing period"
          value={data.current_period ? `${formatDate(data.current_period.period_start)} – ${formatDate(data.current_period.period_end)}` : 'No billing history yet'}
        />
      </div>

      {data.current_period && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
            Current period status
          </div>
          <div style={{ fontSize: 13, color: 'var(--text)' }}>
            Billing period #{data.current_period.billing_period_id} is currently <strong>{data.current_period.status}</strong>.
          </div>
        </Card>
      )}

      <Card>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Cost by service (last 30 days)
        </div>
        <CostBreakdownChart orgId={orgId} />
      </Card>
    </div>
  )
}

// ── Invoices tab: paginated list -> detail. ─────────────────────────────

const PAGE_SIZE = 20

function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null
  const btnBase: React.CSSProperties = {
    fontSize: 12, fontWeight: 600, padding: '5px 12px', borderRadius: 6,
    border: '1px solid var(--border)', background: 'var(--surface)', cursor: 'pointer',
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 0' }}>
      <button onClick={() => onPage(page - 1)} disabled={page === 1}
        style={{ ...btnBase, color: page === 1 ? 'var(--muted)' : 'var(--text2)', opacity: page === 1 ? 0.4 : 1 }}>
        ← Prev
      </button>
      <span style={{ fontSize: 12, color: 'var(--muted)', minWidth: 90, textAlign: 'center' }}>
        Page <span style={{ color: 'var(--text)', fontWeight: 700 }}>{page}</span> of {totalPages}
      </span>
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages}
        style={{ ...btnBase, color: page === totalPages ? 'var(--muted)' : 'var(--text2)', opacity: page === totalPages ? 0.4 : 1 }}>
        Next →
      </button>
    </div>
  )
}

const STATUS_FILTERS = ['ALL', 'DRAFT', 'ISSUED', 'PAID', 'VOID'] as const

function InvoicesTab({ orgId, onSelectInvoice }: { orgId: number; onSelectInvoice: (invoiceId: number) => void }) {
  const [state, setState] = useState<LoadState<{ invoices: InvoiceListItem[]; totalCount: number }>>({ status: 'loading' })
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<typeof STATUS_FILTERS[number]>('ALL')

  const load = () => {
    setState({ status: 'loading' })
    fetchInvoices(orgId, {
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    })
      .then(result => setState({ status: 'ready', data: { invoices: result.invoices, totalCount: result.total_count } }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404' || kind === 'denied-403') setState({ status: 'denied', reason: "This organization's invoices aren't accessible to you." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId, page, statusFilter])

  const totalPages = state.status === 'ready' ? Math.max(1, Math.ceil(state.data.totalCount / PAGE_SIZE)) : 1

  return (
    <div>
      <ActionToolbar>
        {STATUS_FILTERS.map(s => (
          <Button
            key={s}
            variant={statusFilter === s ? 'primary' : 'secondary'}
            onClick={() => { setStatusFilter(s); setPage(1) }}
          >
            {s === 'ALL' ? 'All statuses' : s}
          </Button>
        ))}
      </ActionToolbar>

      <div style={{ marginTop: 12 }}>
        {state.status === 'loading' && <LoadingState label="Loading invoices…" />}
        {state.status === 'denied' && <EmptyState icon={ShieldAlert} title="Permission denied" description={state.reason} />}
        {state.status === 'error' && <ErrorState message={state.message} onRetry={load} />}
        {state.status === 'ready' && (
          <>
            <DataTable
              rowKey={i => i.id}
              emptyLabel="No invoices for this organization yet."
              rows={state.data.invoices}
              columns={[
                { key: 'invoice_number', header: 'Invoice #', render: i => i.invoice_number ?? `#${i.id}` },
                { key: 'period', header: 'Billing period', render: i => `${formatDate(i.period_start)} – ${formatDate(i.period_end)}` },
                { key: 'total', header: 'Total', render: i => formatCurrency(i.total, i.currency) },
                { key: 'status', header: 'Status', render: i => <StatusBadge status={i.status} /> },
                { key: 'created', header: 'Created', render: i => formatDateTime(i.created_at) },
                {
                  key: 'actions', header: '', render: i => (
                    <button
                      onClick={() => onSelectInvoice(i.id)}
                      style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer' }}
                    >
                      View details →
                    </button>
                  ),
                },
              ]}
            />
            <Pagination page={page} totalPages={totalPages} onPage={setPage} />
          </>
        )}
      </div>
    </div>
  )
}

// ── Invoice detail ───────────────────────────────────────────────────────

function InvoiceDetailView({ invoiceId, onBack }: { invoiceId: number; onBack: () => void }) {
  const [state, setState] = useState<LoadState<InvoiceDetail>>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchInvoiceDetail(invoiceId)
      .then(data => setState({ status: 'ready', data }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        // get_authorized_invoice returns 404 (not 403) for a wrong-org
        // invoice, by design -- both render as the same permission-denied
        // variant here, never leaking whether the invoice id exists.
        if (kind === 'denied-404' || kind === 'denied-403') setState({ status: 'denied', reason: "This invoice isn't accessible to you." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [invoiceId])

  return (
    <div>
      <BackLink label="Back to invoices" onBack={onBack} />

      {state.status === 'loading' && <LoadingState label="Loading invoice…" />}
      {state.status === 'denied' && <EmptyState icon={ShieldAlert} title="Permission denied" description={state.reason} />}
      {state.status === 'error' && <ErrorState message={state.message} onRetry={load} />}

      {state.status === 'ready' && (
        <>
          <SectionHeader
            title={state.data.invoice_number ?? `Invoice #${state.data.id}`}
            description={`Billing period ${formatDate(state.data.period_start)} – ${formatDate(state.data.period_end)}`}
            actions={<StatusBadge status={state.data.status} />}
          />

          <Card style={{ marginBottom: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
              <SummaryField title="Subtotal" value={formatCurrency(state.data.subtotal, state.data.currency)} />
              <SummaryField title="Credits" value={formatCurrency(state.data.credits, state.data.currency)} />
              <SummaryField title="Adjustments" value={formatCurrency(state.data.adjustments, state.data.currency)} />
              <SummaryField title="Taxes" value={formatCurrency(state.data.taxes, state.data.currency)} />
              <SummaryField title="Total" value={formatCurrency(state.data.total, state.data.currency)} emphasize />
              <SummaryField title="Issued" value={formatDateTime(state.data.issued_at)} />
              <SummaryField title="Due" value={formatDateTime(state.data.due_at)} />
              <SummaryField title="Paid" value={formatDateTime(state.data.paid_at)} />
            </div>
          </Card>

          <Card>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
              Line items
            </div>
            <DataTable
              rowKey={li => li.id}
              emptyLabel="No line items on this invoice."
              rows={state.data.line_items}
              columns={[
                { key: 'service', header: 'Service', render: li => li.service },
                { key: 'action', header: 'Action', render: li => li.action },
                { key: 'resource', header: 'Resource', render: li => li.resource },
                { key: 'quantity', header: 'Quantity', render: li => `${li.quantity} ${li.unit}` },
                { key: 'unit_price', header: 'Unit price', render: li => formatCurrency(li.unit_price, state.data.currency) },
                { key: 'line_total', header: 'Line total', render: li => formatCurrency(li.line_total, state.data.currency) },
                { key: 'description', header: 'Description', render: li => li.description ?? '—' },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  )
}

function SummaryField({ title, value, emphasize }: { title: string; value: string; emphasize?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: emphasize ? 16 : 13, fontWeight: emphasize ? 700 : 400, color: 'var(--text)' }}>{value}</div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

type Tab = 'overview' | 'invoices'

interface Props {
  orgId: number
  onBack: () => void
}

export default function BillingPage({ orgId, onBack }: Props) {
  const [tab, setTab] = useState<Tab>('overview')
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<number | null>(null)
  const orgLabel = useOrgLabel(orgId)

  // Switching organizations (via the picker) always lands back on
  // Overview with no invoice selected -- same "fresh start" precedent
  // ServiceAccountsPage.tsx's own tab default follows.
  useEffect(() => { setSelectedInvoiceId(null); setTab('overview') }, [orgId])

  if (selectedInvoiceId != null) {
    return (
      <div>
        <BackLink label="Back to billing" onBack={onBack} />
        <SectionHeader title="Billing" description={`Organization-level billing for ${orgLabel}.`} />
        <InvoiceDetailView invoiceId={selectedInvoiceId} onBack={() => setSelectedInvoiceId(null)} />
      </div>
    )
  }

  return (
    <div>
      <BackLink label="Back" onBack={onBack} />
      <SectionHeader title="Billing" description={`Usage, cost, and invoices for ${orgLabel}.`} />

      <Card style={{ padding: 0, marginBottom: 16 }}>
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <TabButton active={tab === 'overview'} icon={Receipt} onClick={() => setTab('overview')}>Overview</TabButton>
          <TabButton active={tab === 'invoices'} icon={FileText} onClick={() => setTab('invoices')}>Invoices</TabButton>
        </div>
        <div style={{ padding: 20 }}>
          {tab === 'overview'
            ? <OverviewTab orgId={orgId} />
            : <InvoicesTab orgId={orgId} onSelectInvoice={setSelectedInvoiceId} />}
        </div>
      </Card>
    </div>
  )
}

function TabButton({ active, icon: Icon, onClick, children }: {
  active: boolean; icon: React.ComponentType<{ size?: number }>; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      style={{
        flex: 1, padding: '12px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        background: 'none', border: 'none', borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
        color: active ? 'var(--text)' : 'var(--muted)',
      }}
    >
      <Icon size={14} />
      {children}
    </button>
  )
}

function BackLink({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <button
      onClick={onBack}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 16,
        fontSize: 12, fontWeight: 600, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer',
      }}
    >
      ← {label}
    </button>
  )
}
