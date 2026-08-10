import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { fetchIntegrations, type IntegrationsResult, type IntegrationStatus } from '../integrations'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState } from '../components/ui'
import StatusBadge from '../components/StatusBadge'

// PR-B6. Flat page, no organization picker, no tabs -- every
// integration this page reads is genuinely platform-wide (an env var on
// control-center's own deployment, not an org-owned resource), same
// reasoning PlatformSettingsPage.tsx already established for
// omnibioai-auth's GlobalConfig.
//
// Read-only, by design, not by omission: discovery for this PR (see its
// own report) found no CRUD API, no credential-input capability, and no
// connection-test mechanism anywhere in the ecosystem for any of these
// three integrations -- there is nothing for a "Configure"/"Test
// Connection"/"Rotate" action to call. Each card says so explicitly
// rather than silently omitting the actions a reviewer might otherwise
// expect to see.
//
// classify()/DeniedState follow PlatformSettingsPage.tsx's own
// convention: GET /integrations requires no permission at all upstream
// (confirmed by reading routes_integrations.py directly -- booleans and
// static labels only, no internal topology, same posture as GET
// /cloud), so a 401 here means the caller's own session has gone stale,
// not a missing permission; there is no 403 case this endpoint can
// produce.

function classify(message: string): 'denied' | 'error' {
  return message.endsWith(' 401') ? 'denied' : 'error'
}

type IntegrationsState =
  | { status: 'loading' }
  | { status: 'denied'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; integrations: IntegrationsResult }

interface CardSpec {
  key: keyof IntegrationsResult
  data: IntegrationStatus
}

function IntegrationCard({ data }: { data: IntegrationStatus }) {
  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{data.label}</div>
        <StatusBadge status={data.configured ? 'configured' : 'not_configured'} />
      </div>
      <p style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 12 }}>{data.purpose}</p>

      {data.report_aggregation_configured !== undefined && (
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
          <span style={{ color: 'var(--text2)' }}>Ecosystem Report error aggregation</span>
          <StatusBadge status={data.report_aggregation_configured ? 'configured' : 'not_configured'} />
        </div>
      )}

      <div style={{ fontSize: 11, color: 'var(--muted)', borderTop: '1px solid var(--border)', paddingTop: 10 }}>
        Managed via deployment environment variables. No in-app configuration, connection test, or credential
        rotation exists for this integration yet.
      </div>
    </Card>
  )
}

export default function IntegrationsPage() {
  const [state, setState] = useState<IntegrationsState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchIntegrations()
      .then(integrations => setState({ status: 'ready', integrations }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', message } : { status: 'error', message })
      })
  }

  useEffect(load, [])

  const cards: CardSpec[] = state.status === 'ready'
    ? (Object.entries(state.integrations) as [keyof IntegrationsResult, IntegrationStatus][])
        .map(([key, data]) => ({ key, data }))
    : []

  return (
    <div>
      <SectionHeader
        title="Integrations"
        description="Third-party integrations wired into this deployment. Read-only -- configuration lives in deployment environment variables, not here."
      />

      {state.status === 'loading' && <LoadingState label="Loading integrations…" />}

      {state.status === 'denied' && (
        <EmptyState
          icon={ShieldAlert}
          title="Session expired"
          description="Your session couldn't be verified. Try refreshing the page."
        />
      )}

      {state.status === 'error' && <ErrorState message={state.message} onRetry={load} />}

      {state.status === 'ready' && cards.length === 0 && (
        <EmptyState title="No integrations found." description="No integration status was returned by the backend." />
      )}

      {state.status === 'ready' && cards.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          {cards.map(({ key, data }) => <IntegrationCard key={key} data={data} />)}
        </div>
      )}
    </div>
  )
}
