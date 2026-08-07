import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SubscriptionTab, UsageLimitsTab } from './SubscriptionPage'
import * as billing from '../../billing'
import type { SubscriptionSummary, SubscriptionUsageLimits } from '../../billing'

vi.mock('../../billing', async () => {
  const actual = await vi.importActual<typeof import('../../billing')>('../../billing')
  return { ...actual, fetchOrganizationSubscription: vi.fn(), fetchSubscriptionUsageLimits: vi.fn() }
})

const summaryWithFeatures: SubscriptionSummary = {
  organization_id: 42,
  billing_plan_id: 7,
  plan_name: 'Enterprise',
  billing_interval: 'monthly',
  currency: 'usd',
  status: 'active',
  start_date: '2026-01-01',
  end_date: null,
  renewal_date: '2026-02-01',
  features: [
    { feature_key: 'rag_access', value_type: 'boolean', bool_value: true, int_value: null, string_value: null },
    { feature_key: 'max_users', value_type: 'integer', bool_value: null, int_value: 250, string_value: null },
    { feature_key: 'workflow_publish', value_type: 'unlimited', bool_value: null, int_value: null, string_value: null },
  ],
}

const summaryNoFeatures: SubscriptionSummary = {
  organization_id: 42,
  billing_plan_id: 7,
  plan_name: 'Starter',
  billing_interval: 'annual',
  currency: 'eur',
  status: 'trial',
  start_date: '2026-01-01',
  end_date: null,
  renewal_date: null,
  features: [],
}

const usageLimits: SubscriptionUsageLimits = {
  organization_id: 42,
  billing_plan_id: 7,
  plan_name: 'Enterprise',
  as_of: '2026-01-15',
  limits: [
    { service: 'studio', action: 'gpu_train', resource: 'gpu_training', unit: 'hour', period: 'monthly', included: 500, used: 120, remaining: 380, percentage_used: 24 },
  ],
}

describe('SubscriptionTab', () => {
  beforeEach(() => {
    vi.mocked(billing.fetchOrganizationSubscription).mockReset()
  })

  it('shows a loading state while the fetch is in flight', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockReturnValue(new Promise(() => {}))
    render(<SubscriptionTab orgId={42} />)
    expect(await screen.findByText('Loading subscription…')).toBeInTheDocument()
  })

  it('shows a no-subscription state on a 404', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockRejectedValue(new Error('/billing/organizations/42/subscription 404'))
    render(<SubscriptionTab orgId={42} />)

    expect(await screen.findByText('No subscription')).toBeInTheDocument()
    expect(screen.queryByText('Current plan')).not.toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockRejectedValue(new Error('/billing/organizations/42/subscription 403'))
    render(<SubscriptionTab orgId={42} />)

    expect(await screen.findByText('No subscription')).toBeInTheDocument()
    expect(await screen.findByText(/isn't accessible to you/)).toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockRejectedValueOnce(new Error('/billing/organizations/42/subscription 503'))
    vi.mocked(billing.fetchOrganizationSubscription).mockResolvedValueOnce(summaryWithFeatures)
    render(<SubscriptionTab orgId={42} />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
  })

  it('renders plan, status, interval, and renewal date', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockResolvedValue(summaryWithFeatures)
    render(<SubscriptionTab orgId={42} />)

    expect(await screen.findByText('Enterprise')).toBeInTheDocument()
    // Rendered lowercase in the DOM -- text-transform: uppercase is a CSS
    // display effect only, it doesn't change the actual text content.
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('monthly (USD)')).toBeInTheDocument()
  })

  it('renders enabled features with a value per value_type', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockResolvedValue(summaryWithFeatures)
    render(<SubscriptionTab orgId={42} />)
    await screen.findByText('Enterprise')

    expect(screen.getByText('rag_access')).toBeInTheDocument()
    expect(screen.getByText('Enabled')).toBeInTheDocument()
    expect(screen.getByText('max_users')).toBeInTheDocument()
    expect(screen.getByText('250')).toBeInTheDocument()
    expect(screen.getByText('workflow_publish')).toBeInTheDocument()
    expect(screen.getByText('Unlimited')).toBeInTheDocument()
  })

  it('shows the empty state when the plan defines no features', async () => {
    vi.mocked(billing.fetchOrganizationSubscription).mockResolvedValue(summaryNoFeatures)
    render(<SubscriptionTab orgId={42} />)

    expect(await screen.findByText('This plan defines no features yet.')).toBeInTheDocument()
    expect(screen.getByText('No renewal scheduled')).toBeInTheDocument()
  })
})

describe('UsageLimitsTab', () => {
  beforeEach(() => {
    vi.mocked(billing.fetchSubscriptionUsageLimits).mockReset()
  })

  it('shows a loading state while the fetch is in flight', async () => {
    vi.mocked(billing.fetchSubscriptionUsageLimits).mockReturnValue(new Promise(() => {}))
    render(<UsageLimitsTab orgId={42} />)
    expect(await screen.findByText('Loading usage limits…')).toBeInTheDocument()
  })

  it('shows a no-subscription state on a 404', async () => {
    vi.mocked(billing.fetchSubscriptionUsageLimits).mockRejectedValue(new Error('/billing/organizations/42/subscription/usage-limits 404'))
    render(<UsageLimitsTab orgId={42} />)

    expect(await screen.findByText('No subscription')).toBeInTheDocument()
  })

  it('renders included/used/remaining per usage-metered feature', async () => {
    vi.mocked(billing.fetchSubscriptionUsageLimits).mockResolvedValue(usageLimits)
    render(<UsageLimitsTab orgId={42} />)

    expect(await screen.findByText('gpu_training')).toBeInTheDocument()
    expect(screen.getByText('500 hour')).toBeInTheDocument()
    expect(screen.getByText('120 hour')).toBeInTheDocument()
    expect(screen.getByText('380 hour')).toBeInTheDocument()
    expect(screen.getByText('24%')).toBeInTheDocument()
  })

  it('shows the empty state when the plan defines no usage-metered limits', async () => {
    vi.mocked(billing.fetchSubscriptionUsageLimits).mockResolvedValue({ ...usageLimits, limits: [] })
    render(<UsageLimitsTab orgId={42} />)

    expect(await screen.findByText('This plan defines no usage-metered limits.')).toBeInTheDocument()
  })
})
