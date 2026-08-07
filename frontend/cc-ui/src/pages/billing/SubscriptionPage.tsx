import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchOrganizationSubscription, fetchSubscriptionUsageLimits,
  type SubscriptionSummary, type SubscriptionUsageLimits, type SubscriptionFeature,
} from '../../billing'
import { Card, SectionHeader, StatCard, DataTable, LoadingState, ErrorState, EmptyState } from '../../components/ui'
import { classify, formatDate, type LoadState } from './BillingPage'

// PR14.6D: Subscription + Usage Limits tabs, wired into BillingPage.tsx
// alongside its existing Overview/Invoices tabs -- same "Organization >
// Billing > ..." destination the task's own nav sketch describes,
// implemented as two more tabs on the page that already owns that
// destination rather than two new top-level nav entries (no new
// frontend architecture, per this PR's own scope). Reuses BillingPage.tsx's
// classify/formatDate/LoadState (see that file's own export comment) --
// not a second copy of the 403/404 "permission denied" classification
// or date formatting.

const SUBSCRIPTION_STATUS_COLOR: Record<string, string> = {
  trial: 'var(--blue, #0094ff)',
  active: 'var(--color-success, #22c55e)',
  suspended: 'var(--amber, #f59e0b)',
  cancelled: 'var(--red)',
}

function SubscriptionStatusBadge({ status }: { status: string }) {
  const color = SUBSCRIPTION_STATUS_COLOR[status] ?? 'var(--muted)'
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color, background: 'var(--bg2)',
      border: `1px solid ${color}`, borderRadius: 999, padding: '2px 9px', textTransform: 'uppercase',
    }}>
      {status}
    </span>
  )
}

/** One plan_features row rendered as a single display value -- exactly
 * one of bool_value/int_value/string_value is meaningful, selected by
 * value_type, same contract app/schemas/subscriptions.py's
 * SubscriptionFeatureItem documents (mirrored here, not re-derived). */
function featureValueLabel(feature: SubscriptionFeature): string {
  switch (feature.value_type) {
    case 'boolean': return feature.bool_value ? 'Enabled' : 'Disabled'
    case 'integer': return feature.int_value != null ? String(feature.int_value) : '—'
    case 'unlimited': return 'Unlimited'
    case 'string': return feature.string_value ?? '—'
    default: return '—'
  }
}

export function SubscriptionTab({ orgId }: { orgId: number }) {
  const [state, setState] = useState<LoadState<SubscriptionSummary>>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchOrganizationSubscription(orgId)
      .then(data => setState({ status: 'ready', data }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404') setState({ status: 'denied', reason: 'This organization has no active subscription.' })
        else if (kind === 'denied-403') setState({ status: 'denied', reason: "This organization's subscription isn't accessible to you." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId])

  if (state.status === 'loading') return <LoadingState label="Loading subscription…" />
  if (state.status === 'denied') return <EmptyState icon={ShieldAlert} title="No subscription" description={state.reason} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { data } = state
  return (
    <div>
      <SectionHeader
        title="Subscription"
        description={`Started ${formatDate(data.start_date)}.`}
        actions={<SubscriptionStatusBadge status={data.status} />}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 20 }}>
        <StatCard label="Current plan" value={data.plan_name} />
        <StatCard label="Billing interval" value={`${data.billing_interval} (${data.currency.toUpperCase()})`} />
        <StatCard label="Renewal date" value={data.renewal_date ? formatDate(data.renewal_date) : 'No renewal scheduled'} />
        <StatCard label="End date" value={data.end_date ? formatDate(data.end_date) : 'Not scheduled'} />
      </div>

      <Card>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Enabled features
        </div>
        <DataTable
          rowKey={f => f.feature_key}
          emptyLabel="This plan defines no features yet."
          rows={data.features}
          columns={[
            { key: 'feature_key', header: 'Feature', render: f => f.feature_key },
            { key: 'value', header: 'Value', render: f => featureValueLabel(f) },
          ]}
        />
      </Card>
    </div>
  )
}

export function UsageLimitsTab({ orgId }: { orgId: number }) {
  const [state, setState] = useState<LoadState<SubscriptionUsageLimits>>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchSubscriptionUsageLimits(orgId)
      .then(data => setState({ status: 'ready', data }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classify(message)
        if (kind === 'denied-404') setState({ status: 'denied', reason: 'This organization has no active subscription.' })
        else if (kind === 'denied-403') setState({ status: 'denied', reason: "This organization's usage limits aren't accessible to you." })
        else setState({ status: 'error', message })
      })
  }

  useEffect(load, [orgId])

  if (state.status === 'loading') return <LoadingState label="Loading usage limits…" />
  if (state.status === 'denied') return <EmptyState icon={ShieldAlert} title="No subscription" description={state.reason} />
  if (state.status === 'error') return <ErrorState message={state.message} onRetry={load} />

  const { data } = state
  return (
    <div>
      <SectionHeader title="Usage limits" description={`As of ${formatDate(data.as_of)}, for ${data.plan_name}.`} />
      <Card>
        <DataTable
          rowKey={l => `${l.service}.${l.action}.${l.resource}`}
          emptyLabel="This plan defines no usage-metered limits."
          rows={data.limits}
          columns={[
            { key: 'resource', header: 'Feature', render: l => l.resource },
            { key: 'included', header: 'Limit', render: l => `${l.included} ${l.unit}` },
            { key: 'used', header: 'Current usage', render: l => `${l.used} ${l.unit}` },
            { key: 'remaining', header: 'Remaining', render: l => `${l.remaining} ${l.unit}` },
            { key: 'percentage_used', header: '% used', render: l => `${l.percentage_used}%` },
          ]}
        />
      </Card>
    </div>
  )
}
