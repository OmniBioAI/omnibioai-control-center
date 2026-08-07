import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { fetchPlatformConfig, type PlatformConfig } from '../platform_config'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState } from '../components/ui'

// PR E1 (Admin Settings integration). Flat page, no organization picker,
// no tabs -- omnibioai-auth's GlobalConfig is genuinely platform-wide,
// not org-scoped, and has few enough fields that one view is sufficient
// (same reasoning RAGPage.tsx's Query Service Status tab already
// established for a small, flat status/config view).
//
// Read-only: no edit form in this PR. See platform_config.ts's and
// routes_platform_config_proxy.py's own module comments for the
// deliberate "read-only first" scope decision -- omnibioai-auth's own
// PUT /auth/config (manage_config-gated) can set a platform-wide LLM
// API key and cloud credentials, and shipping that write path is
// explicitly deferred to its own follow-up PR, not bundled into this
// one.
//
// classify()/DeniedState follow ToolExecutionPage.tsx's own convention:
// distinguish "no permission" from a genuine error by the thrown
// message's trailing status suffix. Unlike every org-scoped page in
// this app, GET /auth/config requires no permission at all upstream --
// only a valid token (confirmed by reading omnibioai-auth's own
// app/api/routes_config.py) -- so a 401 here means the caller's own
// session has gone stale, not a missing permission; there is no 403
// case this endpoint can produce.

function classify(message: string): 'denied' | 'error' {
  return message.endsWith(' 401') ? 'denied' : 'error'
}

function configuredLabel(configured: boolean): string {
  return configured ? 'Configured' : 'Not configured'
}

function formatDateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10, display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
      <span style={{ color: 'var(--text2)' }}>{title}</span>
      <span style={{ color: 'var(--text)', fontWeight: 600 }}>{children}</span>
    </div>
  )
}

type ConfigState =
  | { status: 'loading' }
  | { status: 'denied'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; config: PlatformConfig }

export default function PlatformSettingsPage() {
  const [state, setState] = useState<ConfigState>({ status: 'loading' })

  const load = () => {
    setState({ status: 'loading' })
    fetchPlatformConfig()
      .then(config => setState({ status: 'ready', config }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        setState(classify(message) === 'denied' ? { status: 'denied', message } : { status: 'error', message })
      })
  }

  useEffect(load, [])

  return (
    <div>
      <SectionHeader
        title="Settings"
        description="Platform-wide configuration, served by omnibioai-auth. Read-only -- editing is not yet available here."
      />

      {state.status === 'loading' && <LoadingState label="Loading platform settings…" />}

      {state.status === 'denied' && (
        <EmptyState
          icon={ShieldAlert}
          title="Session expired"
          description="Your session couldn't be verified. Try refreshing the page."
        />
      )}

      {state.status === 'error' && <ErrorState message={state.message} onRetry={load} />}

      {state.status === 'ready' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>AI / LLM</div>
            <Field title="Provider">{state.config.llm_provider ?? 'Not configured'}</Field>
            <Field title="API Key">{configuredLabel(state.config.has_llm_api_key)}</Field>
          </Card>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Cloud</div>
            <Field title="Provider">{state.config.cloud_provider ?? 'Not configured'}</Field>
            <Field title="Credentials">{configuredLabel(state.config.has_cloud_credentials)}</Field>
          </Card>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Storage Paths</div>
            <Field title="Work Directory">{state.config.work_directory ?? 'Not configured'}</Field>
            <Field title="Data Directory">{state.config.data_directory ?? 'Not configured'}</Field>
          </Card>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Last Updated</div>
            <Field title="When">{formatDateTime(state.config.updated_at)}</Field>
            <Field title="By">{state.config.updated_by_email ?? '—'}</Field>
          </Card>
        </div>
      )}
    </div>
  )
}
