import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import BillingPage from './BillingPage'
import * as auth from '../../auth'
import * as billing from '../../billing'
import type { OrganizationBillingSummary, InvoiceListResult, InvoiceDetail } from '../../billing'
import * as organizations from '../../organizations'
import type { MyOrg } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../billing', async () => {
  const actual = await vi.importActual<typeof import('../../billing')>('../../billing')
  return {
    ...actual,
    fetchOrganizationBillingSummary: vi.fn(),
    fetchInvoices: vi.fn(),
    fetchInvoiceDetail: vi.fn(),
    fetchCostBreakdown: vi.fn(),
  }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchMyOrg: vi.fn(), fetchPlatformOrgDetail: vi.fn() }
})

// recharts' ResponsiveContainer relies on ResizeObserver, which jsdom
// doesn't implement -- stubbed out with simple passthrough components so
// CostBreakdownChart's own data-shaping logic can be exercised without
// pulling in a jsdom polyfill this repo doesn't otherwise need.
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="chart-container">{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
}))

const myOrg: MyOrg = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

const summaryWithPeriod: OrganizationBillingSummary = {
  organization_id: 42,
  current_period: { billing_period_id: 7, period_start: '2026-08-01', period_end: '2026-08-31', status: 'OPEN' },
  current_usage_cost: 123.45,
  currency: 'usd',
  invoice_count: 3,
  outstanding_amount: 50,
}

const summaryNoHistory: OrganizationBillingSummary = {
  organization_id: 42,
  current_period: null,
  current_usage_cost: 0,
  currency: 'usd',
  invoice_count: 0,
  outstanding_amount: 0,
}

const invoiceListResult: InvoiceListResult = {
  organization_id: 42,
  total_count: 1,
  limit: 20,
  offset: 0,
  invoices: [{
    id: 99, invoice_number: 'INV-0099', billing_period_id: 7,
    period_start: '2026-08-01', period_end: '2026-08-31', status: 'ISSUED',
    subtotal: 100, total: 110, currency: 'usd', created_at: '2026-09-01T00:00:00',
  }],
}

const invoiceDetail: InvoiceDetail = {
  id: 99, invoice_number: 'INV-0099', organization_id: 42, billing_period_id: 7,
  period_start: '2026-08-01', period_end: '2026-08-31', status: 'ISSUED', currency: 'usd',
  subtotal: 100, credits: 0, adjustments: 0, taxes: 10, total: 110,
  issued_at: '2026-09-01T00:00:00', due_at: null, paid_at: null, created_at: '2026-09-01T00:00:00',
  line_items: [{
    id: 1, rated_usage_record_id: 501, service: 'tes', action: 'run_task', resource: 'task',
    unit: 'task', quantity: 5, unit_price: 20, line_total: 100, description: null,
  }],
}

describe('BillingPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(billing.fetchOrganizationBillingSummary).mockReset()
    vi.mocked(billing.fetchInvoices).mockReset()
    vi.mocked(billing.fetchInvoiceDetail).mockReset()
    vi.mocked(billing.fetchCostBreakdown).mockReset()
    vi.mocked(billing.fetchCostBreakdown).mockResolvedValue({
      organization_id: 42, period_start: '2026-07-07', period_end: '2026-08-06',
      group_by: 'service', currency: 'usd', breakdown: {},
    })
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
  })

  // ── Overview tab ────────────────────────────────────────────────────

  it('shows a loading state while the summary fetch is in flight', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockReturnValue(new Promise(() => {}))
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('Loading billing summary…')).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not the summary', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockRejectedValue(new Error('/billing/organizations/42/summary 403'))
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('Current period usage')).not.toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockRejectedValueOnce(new Error('/billing/organizations/42/summary 503'))
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValueOnce(summaryWithPeriod)
    const user = userEvent.setup()
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Current period usage')).toBeInTheDocument()
  })

  it('renders the summary stat cards and current period status', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Current period usage')).toBeInTheDocument()
    expect(screen.getByText('$123.45')).toBeInTheDocument()
    expect(screen.getByText('$50.00')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText(/Billing period #7 is currently/)).toBeInTheDocument()
    expect(screen.getByText('OPEN')).toBeInTheDocument()
  })

  it('shows "No billing history yet" when the organization has no current period', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryNoHistory)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('No billing history yet')).toBeInTheDocument()
    // No period status card renders without a current_period.
    expect(screen.queryByText(/is currently/)).not.toBeInTheDocument()
  })

  it('shows the empty state when the cost breakdown has no entries', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchCostBreakdown).mockResolvedValue({
      organization_id: 42, period_start: '2026-07-07', period_end: '2026-08-06',
      group_by: 'service', currency: 'usd', breakdown: {},
    })
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('No usage in the last 30 days')).toBeInTheDocument()
  })

  it('renders the chart container when the cost breakdown has entries', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchCostBreakdown).mockResolvedValue({
      organization_id: 42, period_start: '2026-07-07', period_end: '2026-08-06',
      group_by: 'service', currency: 'usd',
      breakdown: { tes: { quantity: 10, cost: 80 }, rag: { quantity: 2, cost: 20 } },
    })
    render(<BillingPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByTestId('chart-container')).toBeInTheDocument()
  })

  // ── Invoices tab ────────────────────────────────────────────────────

  it('lists invoices with a status badge and total', async () => {
    const user = userEvent.setup()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockResolvedValue(invoiceListResult)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')

    await user.click(screen.getByRole('button', { name: /Invoices/ }))

    expect(await screen.findByText('INV-0099')).toBeInTheDocument()
    expect(screen.getByText('$110.00')).toBeInTheDocument()
    // 'ISSUED' appears twice: the status filter button and the row's own
    // status badge -- both are already the desired label, no need to
    // pick one apart from the other any further here.
    expect(screen.getAllByText('ISSUED').length).toBe(2)
  })

  it('refetches with the selected status filter', async () => {
    const user = userEvent.setup()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockResolvedValue(invoiceListResult)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')
    await user.click(screen.getByRole('button', { name: /Invoices/ }))
    await screen.findByText('INV-0099')

    await user.click(screen.getByRole('button', { name: 'PAID' }))

    await waitFor(() => expect(billing.fetchInvoices).toHaveBeenCalledWith(42, { status: 'PAID', limit: 20, offset: 0 }))
  })

  it('shows a permission-denied state for the invoice list on a 404', async () => {
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockRejectedValue(new Error('/billing/organizations/42/invoices 404'))
    const user = userEvent.setup()
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')

    await user.click(screen.getByRole('button', { name: /Invoices/ }))

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  // ── Invoice detail ──────────────────────────────────────────────────

  it('opens invoice detail from the list and shows line items', async () => {
    const user = userEvent.setup()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockResolvedValue(invoiceListResult)
    vi.mocked(billing.fetchInvoiceDetail).mockResolvedValue(invoiceDetail)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')
    await user.click(screen.getByRole('button', { name: /Invoices/ }))
    await screen.findByText('INV-0099')

    await user.click(screen.getByRole('button', { name: 'View details →' }))

    expect(billing.fetchInvoiceDetail).toHaveBeenCalledWith(99)
    expect(await screen.findByText('tes')).toBeInTheDocument()
    expect(screen.getByText('run_task')).toBeInTheDocument()
    expect(screen.getByText('5 task')).toBeInTheDocument()
  })

  it('shows a permission-denied state for a wrong-org invoice (404, not 403)', async () => {
    const user = userEvent.setup()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockResolvedValue(invoiceListResult)
    vi.mocked(billing.fetchInvoiceDetail).mockRejectedValue(new Error('/billing/invoices/99 404'))
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')
    await user.click(screen.getByRole('button', { name: /Invoices/ }))
    await screen.findByText('INV-0099')
    await user.click(screen.getByRole('button', { name: 'View details →' }))

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  it('returns to the invoice list when "Back to invoices" is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    vi.mocked(billing.fetchInvoices).mockResolvedValue(invoiceListResult)
    vi.mocked(billing.fetchInvoiceDetail).mockResolvedValue(invoiceDetail)
    render(<BillingPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current period usage')
    await user.click(screen.getByRole('button', { name: /Invoices/ }))
    await screen.findByText('INV-0099')
    await user.click(screen.getByRole('button', { name: 'View details →' }))
    await screen.findByText('run_task')

    await user.click(screen.getByRole('button', { name: '← Back to invoices' }))

    expect(await screen.findByText('INV-0099')).toBeInTheDocument()
  })

  it('calls onBack when the top-level back link is clicked', async () => {
    const onBack = vi.fn()
    vi.mocked(billing.fetchOrganizationBillingSummary).mockResolvedValue(summaryWithPeriod)
    const user = userEvent.setup()
    render(<BillingPage orgId={42} onBack={onBack} />)
    await screen.findByText('Current period usage')

    await user.click(screen.getByRole('button', { name: '← Back' }))

    expect(onBack).toHaveBeenCalled()
  })
})
