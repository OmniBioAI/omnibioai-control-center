import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import IntegrationsPage from './IntegrationsPage'
import * as integrations from '../integrations'
import type { IntegrationsResult } from '../integrations'

vi.mock('../integrations', async () => {
  const actual = await vi.importActual<typeof import('../integrations')>('../integrations')
  return { ...actual, fetchIntegrations: vi.fn() }
})

const allConfigured: IntegrationsResult = {
  sentry: {
    label: 'Sentry',
    purpose: 'Error tracking (SDK crash reporting) and error aggregation for the Ecosystem Report',
    configured: true,
    report_aggregation_configured: true,
  },
  discord_notifications: {
    label: 'Discord – Notifications',
    purpose: 'General deploy, GPU-temperature, and disk-space alerts',
    configured: true,
  },
  discord_alerts: {
    label: 'Discord – Known-Issue Alerts',
    purpose: 'High-severity known-issue alerts, separate from general notifications',
    configured: false,
  },
}

const noneConfigured: IntegrationsResult = {
  sentry: {
    label: 'Sentry',
    purpose: 'Error tracking (SDK crash reporting) and error aggregation for the Ecosystem Report',
    configured: false,
    report_aggregation_configured: false,
  },
  discord_notifications: {
    label: 'Discord – Notifications',
    purpose: 'General deploy, GPU-temperature, and disk-space alerts',
    configured: false,
  },
  discord_alerts: {
    label: 'Discord – Known-Issue Alerts',
    purpose: 'High-severity known-issue alerts, separate from general notifications',
    configured: false,
  },
}

describe('IntegrationsPage', () => {
  beforeEach(() => {
    vi.mocked(integrations.fetchIntegrations).mockReset()
  })

  it('shows a loading state while integrations are in flight', async () => {
    vi.mocked(integrations.fetchIntegrations).mockReturnValue(new Promise(() => {}))
    render(<IntegrationsPage />)
    expect(await screen.findByText('Loading integrations…')).toBeInTheDocument()
  })

  it('renders every integration returned, with its label and purpose', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)

    expect(await screen.findByText('Sentry')).toBeInTheDocument()
    expect(screen.getByText('Discord – Notifications')).toBeInTheDocument()
    expect(screen.getByText('Discord – Known-Issue Alerts')).toBeInTheDocument()
    expect(screen.getByText(/Error tracking \(SDK crash reporting\)/)).toBeInTheDocument()
  })

  it('renders CONFIGURED/NOT CONFIGURED status per integration, not a single aggregate badge', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    // sentry (top) + discord_notifications (top) + sentry's own report-
    // aggregation sub-flag = 3 configured; discord_alerts (top) = 1 not.
    expect(screen.getAllByText('configured')).toHaveLength(3)
    expect(screen.getAllByText('not_configured')).toHaveLength(1)
  })

  it('shows not_configured for every integration when none are set', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(noneConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    // 3 top-level cards + sentry's own report-aggregation sub-flag = 4
    expect(screen.getAllByText('not_configured')).toHaveLength(4)
  })

  it('shows the sentry-only report-aggregation flag, not on discord cards', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    expect(screen.getByText('Ecosystem Report error aggregation')).toBeInTheDocument()
  })

  it('states why actions are unavailable, on every card', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    expect(screen.getAllByText(/No in-app configuration, connection test, or credential rotation exists/))
      .toHaveLength(3)
  })

  it('never renders a configure/edit/test-connection/rotate action -- none exist to call', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    expect(screen.queryByRole('button', { name: /configure|edit|test connection|rotate|delete/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('never renders a credential/secret/token/webhook-URL value', async () => {
    vi.mocked(integrations.fetchIntegrations).mockResolvedValue(allConfigured)
    render(<IntegrationsPage />)
    await screen.findByText('Sentry')

    expect(screen.queryByText(/discord\.com\/api\/webhooks/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/sentry\.io\/[^/]+\/[0-9]+/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/\bsk-\w|Bearer\s+\S+/i)).not.toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a generic error', async () => {
    vi.mocked(integrations.fetchIntegrations).mockRejectedValue(new Error('/integrations 401'))
    render(<IntegrationsPage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures, and recovers on retry', async () => {
    vi.mocked(integrations.fetchIntegrations).mockRejectedValueOnce(new Error('/integrations 503'))
    vi.mocked(integrations.fetchIntegrations).mockResolvedValueOnce(allConfigured)
    const user = userEvent.setup()
    render(<IntegrationsPage />)

    expect(await screen.findByText('/integrations 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    expect(await screen.findByText('Sentry')).toBeInTheDocument()
  })
})
