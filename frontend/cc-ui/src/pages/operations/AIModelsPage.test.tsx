import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AIModelsPage from './AIModelsPage'
import * as modelRegistry from '../../model_registry'
import type { ModelVersionRow, ModelRegistryHealth, ModelRegistryAuthStatus } from '../../model_registry'

vi.mock('../../model_registry', async () => {
  const actual = await vi.importActual<typeof import('../../model_registry')>('../../model_registry')
  return {
    ...actual,
    fetchModels: vi.fn(),
    fetchModelRegistryHealth: vi.fn(),
    fetchModelRegistryAuthStatus: vi.fn(),
  }
})

const modelVersions: ModelVersionRow[] = [
  { task: 'classification', model_name: 'tissue-classifier', version: '1.0.0', created_at: '2026-07-01T00:00:00', stage: 'production' },
  { task: 'classification', model_name: 'tissue-classifier', version: '1.1.0', created_at: '2026-08-01T00:00:00' },
]

const health: ModelRegistryHealth = { ok: true, service: 'omnibioai-model-registry', version: '1.4.0' }
const authStatus: ModelRegistryAuthStatus = { auth_enabled: true, mode: 'jwt', iam_url: 'http://auth-service:8001' }

describe('AIModelsPage', () => {
  beforeEach(() => {
    vi.mocked(modelRegistry.fetchModels).mockReset()
    vi.mocked(modelRegistry.fetchModelRegistryHealth).mockReset().mockResolvedValue(health)
    vi.mocked(modelRegistry.fetchModelRegistryAuthStatus).mockReset().mockResolvedValue(authStatus)
  })

  it('shows a loading state while models are in flight', async () => {
    vi.mocked(modelRegistry.fetchModels).mockReturnValue(new Promise(() => {}))
    render(<AIModelsPage />)
    expect(await screen.findByText('Loading registered models…')).toBeInTheDocument()
  })

  it('shows the empty state when no models are registered yet', async () => {
    vi.mocked(modelRegistry.fetchModels).mockResolvedValue([])
    render(<AIModelsPage />)
    expect(await screen.findByText('No models registered yet.')).toBeInTheDocument()
  })

  it('renders the Registered Models tab grouped by task+model_name', async () => {
    vi.mocked(modelRegistry.fetchModels).mockResolvedValue(modelVersions)
    render(<AIModelsPage />)

    expect(await screen.findByRole('columnheader', { name: 'Model Name' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Versions' })).toBeInTheDocument()
    expect(screen.getByText('tissue-classifier')).toBeInTheDocument()
    // Two version rows for the same (task, model_name) collapse into one group row.
    expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument()
  })

  it('shows permission-denied when the backend 403s', async () => {
    vi.mocked(modelRegistry.fetchModels).mockRejectedValue(new Error('/model-registry/models 403'))
    render(<AIModelsPage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('No models registered yet.')).not.toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(modelRegistry.fetchModels).mockRejectedValueOnce(new Error('/model-registry/models 503'))
    vi.mocked(modelRegistry.fetchModels).mockResolvedValueOnce(modelVersions)
    const user = userEvent.setup()
    render(<AIModelsPage />)

    expect(await screen.findByText('/model-registry/models 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByText('tissue-classifier')).toBeInTheDocument())
  })

  it('switches to the Model Versions tab and shows one row per version', async () => {
    vi.mocked(modelRegistry.fetchModels).mockResolvedValue(modelVersions)
    const user = userEvent.setup()
    render(<AIModelsPage />)
    await screen.findByText('tissue-classifier')

    await user.click(screen.getByRole('button', { name: 'Model Versions' }))

    expect(await screen.findByRole('columnheader', { name: 'Version' })).toBeInTheDocument()
    expect(screen.getByText('1.0.0')).toBeInTheDocument()
    expect(screen.getByText('1.1.0')).toBeInTheDocument()
    // CSS text-transform: uppercase is visual only -- the DOM text
    // content itself stays as the raw stage value.
    expect(screen.getByText('production')).toBeInTheDocument()
  })

  it('switches to the Runtime Status tab and shows health + auth status', async () => {
    vi.mocked(modelRegistry.fetchModels).mockResolvedValue([])
    const user = userEvent.setup()
    render(<AIModelsPage />)
    await screen.findByText('No models registered yet.')

    await user.click(screen.getByRole('button', { name: 'Runtime Status' }))

    expect(await screen.findByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText('omnibioai-model-registry')).toBeInTheDocument()
    expect(screen.getByText('jwt')).toBeInTheDocument()
  })
})
