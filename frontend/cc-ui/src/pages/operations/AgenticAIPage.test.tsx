import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AgenticAIPage from './AgenticAIPage'
import * as agentOrchestrator from '../../agent_orchestrator'
import type { AgentGraph } from '../../agent_orchestrator'

vi.mock('../../agent_orchestrator', async () => {
  const actual = await vi.importActual<typeof import('../../agent_orchestrator')>('../../agent_orchestrator')
  return {
    ...actual,
    fetchAgentGraphs: vi.fn(),
  }
})

const graphs: AgentGraph[] = [
  {
    graph_id: 'de_analysis',
    display_name: 'Differential Expression',
    description: 'DE: quant -> DESeq2 -> volcano -> summary',
    version: '0.1.0',
    enabled: true,
    inputs_schema: {},
    dag: {
      nodes: [
        { id: 'counts', label: 'Counts/Matrix' },
        { id: 'rnaseq_analysis', label: 'DESeq2 (RNA-seq Analysis)', plugin: 'rnaseq_analysis' },
      ],
      edges: [{ from: 'counts', to: 'rnaseq_analysis' }],
    },
  },
  {
    graph_id: 'refdb_react_agent',
    display_name: 'Reference-DB Evidence Agent (ReAct)',
    description: 'ReAct-style evidence lookup agent.',
    version: '0.1.0',
    enabled: true,
    inputs_schema: {},
    dag: null,
  },
  {
    graph_id: 'drug_discovery_composite_agent',
    display_name: 'Drug Discovery Composite Agent',
    description: 'Composite agent chaining multiple sub-agents.',
    version: '0.1.0',
    enabled: true,
    inputs_schema: {},
    dag: null,
  },
]

describe('AgenticAIPage', () => {
  beforeEach(() => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockReset()
  })

  it('shows a loading state while graphs are in flight', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockReturnValue(new Promise(() => {}))
    render(<AgenticAIPage />)
    expect(await screen.findByText('Loading agent graphs…')).toBeInTheDocument()
  })

  it('shows the empty state when the catalog is empty', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockResolvedValue([])
    render(<AgenticAIPage />)
    expect(await screen.findByText('No agent graphs returned')).toBeInTheDocument()
  })

  it('groups real graphs by architecture type with real stat counts', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockResolvedValue(graphs)
    render(<AgenticAIPage />)

    expect(await screen.findByText('Total Agent Graphs')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    // "Fixed Pipelines"/"ReAct Agents"/"Composite Agents" each appear
    // twice (StatCard label + group header) -- assert presence, not
    // uniqueness, that's covered by the row-level assertions below.
    expect(screen.getAllByText(/Fixed Pipelines/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/ReAct Agents/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Composite Agents/).length).toBeGreaterThan(0)
    expect(screen.getByText('Differential Expression')).toBeInTheDocument()
    expect(screen.getByText('Reference-DB Evidence Agent (ReAct)')).toBeInTheDocument()
    expect(screen.getByText('Drug Discovery Composite Agent')).toBeInTheDocument()
  })

  it('never fabricates run history -- drill-in shows an explicit not-yet-connected state', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockResolvedValue(graphs)
    const user = userEvent.setup()
    render(<AgenticAIPage />)
    await screen.findByText('Differential Expression')

    await user.click(screen.getByRole('button', { name: 'Differential Expression' }))

    expect(await screen.findByText('Not yet connected to live run data')).toBeInTheDocument()
    expect(screen.queryByText(/ago$/)).not.toBeInTheDocument()
  })

  it('renders the real DAG nodes/edges on drill-in, not invented ones', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockResolvedValue(graphs)
    const user = userEvent.setup()
    render(<AgenticAIPage />)
    await screen.findByText('Differential Expression')

    await user.click(screen.getByRole('button', { name: 'Differential Expression' }))

    expect(await screen.findByText('Counts/Matrix')).toBeInTheDocument()
    expect(screen.getByText('DESeq2 (RNA-seq Analysis)')).toBeInTheDocument()
  })

  it('shows a session-expired state when the backend 401s', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockRejectedValue(new Error('/agent-orchestrator/graphs 401'))
    render(<AgenticAIPage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockRejectedValueOnce(new Error('/agent-orchestrator/graphs 503'))
    vi.mocked(agentOrchestrator.fetchAgentGraphs).mockResolvedValueOnce(graphs)
    const user = userEvent.setup()
    render(<AgenticAIPage />)

    expect(await screen.findByText('/agent-orchestrator/graphs 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByText('Differential Expression')).toBeInTheDocument())
  })
})
