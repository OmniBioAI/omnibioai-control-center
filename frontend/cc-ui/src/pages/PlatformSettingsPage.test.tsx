import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import PlatformSettingsPage from './PlatformSettingsPage'
import * as platformConfig from '../platform_config'
import type { PlatformConfig } from '../platform_config'

vi.mock('../platform_config', async () => {
  const actual = await vi.importActual<typeof import('../platform_config')>('../platform_config')
  return { ...actual, fetchPlatformConfig: vi.fn() }
})

const configuredConfig: PlatformConfig = {
  llm_provider: 'anthropic', has_llm_api_key: true,
  cloud_provider: 'aws', has_cloud_credentials: true,
  work_directory: '/workspace/work', data_directory: '/workspace/data',
  updated_at: '2026-08-01T10:00:00', updated_by_email: 'admin@omnibioai.org',
}

const unsetConfig: PlatformConfig = {
  llm_provider: null, has_llm_api_key: false,
  cloud_provider: null, has_cloud_credentials: false,
  work_directory: null, data_directory: null,
  updated_at: null, updated_by_email: null,
}

describe('PlatformSettingsPage', () => {
  beforeEach(() => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockReset()
  })

  it('shows a loading state while config is in flight', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockReturnValue(new Promise(() => {}))
    render(<PlatformSettingsPage />)
    expect(await screen.findByText('Loading platform settings…')).toBeInTheDocument()
  })

  it('shows "Not configured" for every field when nothing has ever been set', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockResolvedValue(unsetConfig)
    render(<PlatformSettingsPage />)

    // All 6 fields (LLM provider, LLM API key, cloud provider, cloud
    // credentials, work directory, data directory) fall back to "Not
    // configured" when null/false.
    expect(await screen.findAllByText('Not configured')).toHaveLength(6)
  })

  it('renders real configured values, never fabricating a credential value', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockResolvedValue(configuredConfig)
    render(<PlatformSettingsPage />)

    expect(await screen.findByText('anthropic')).toBeInTheDocument()
    expect(screen.getByText('aws')).toBeInTheDocument()
    expect(screen.getByText('/workspace/work')).toBeInTheDocument()
    expect(screen.getByText('/workspace/data')).toBeInTheDocument()
    expect(screen.getAllByText('Configured')).toHaveLength(2)
    expect(screen.getByText('admin@omnibioai.org')).toBeInTheDocument()
    // No credential value ever appears -- the response shape has none to
    // begin with (has_llm_api_key/has_cloud_credentials are booleans).
    expect(screen.queryByText(/sk-|api[_-]?key.*:.*\w{10}/i)).not.toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a generic error', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockRejectedValue(new Error('/auth/config 401'))
    render(<PlatformSettingsPage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockRejectedValueOnce(new Error('/auth/config 503'))
    vi.mocked(platformConfig.fetchPlatformConfig).mockResolvedValueOnce(configuredConfig)
    const user = userEvent.setup()
    render(<PlatformSettingsPage />)

    expect(await screen.findByText('/auth/config 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    expect(await screen.findByText('anthropic')).toBeInTheDocument()
  })

  it('never renders an edit control -- this PR is read-only', async () => {
    vi.mocked(platformConfig.fetchPlatformConfig).mockResolvedValue(configuredConfig)
    render(<PlatformSettingsPage />)
    await screen.findByText('anthropic')

    expect(screen.queryByRole('button', { name: /save|edit|update/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
