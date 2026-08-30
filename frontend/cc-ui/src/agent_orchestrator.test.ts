import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchAgentGraphs, classifyArchitecture } from './agent_orchestrator'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({})), reportUnauthorized: vi.fn() }
})

describe('fetchAgentGraphs', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('unwraps the upstream {"graphs": [...]} envelope into a flat array', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ graphs: [{ graph_id: 'de_analysis' }] }), { status: 200 }),
    )
    const rows = await fetchAgentGraphs()
    expect(rows).toEqual([{ graph_id: 'de_analysis' }])
  })

  it('returns an empty array rather than throwing if the envelope shape is unexpected', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    const rows = await fetchAgentGraphs()
    expect(rows).toEqual([])
  })

  it('surfaces a real backend error message on failure', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ error: 'workbench-service unreachable: ConnectError' }), { status: 503 }),
    )
    await expect(fetchAgentGraphs()).rejects.toThrow('workbench-service unreachable: ConnectError')
  })
})

describe('classifyArchitecture', () => {
  it('classifies a "(ReAct)" display_name as react_agent', () => {
    expect(classifyArchitecture({ display_name: 'Reference-DB Evidence Agent (ReAct)', description: '' })).toBe('react_agent')
  })

  it('classifies a "composite" display_name as composite', () => {
    expect(classifyArchitecture({ display_name: 'Drug Discovery Composite Agent', description: '' })).toBe('composite')
  })

  it('falls back to fixed_pipeline for a plain hand-authored DAG', () => {
    expect(classifyArchitecture({ display_name: 'Differential Expression', description: 'quant -> DESeq2 -> volcano' })).toBe('fixed_pipeline')
  })
})
