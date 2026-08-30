// Agentic AI nav item (feature/agentic-ai-navbar): data layer mirroring
// tes.ts's/model_registry.ts's shape exactly. Every call hits control-
// center's own backend at a relative path (routes_agent_orchestrator_
// proxy.py proxies the /agent-orchestrator/* surface to
// omnibioai-workbench's agent_orchestrator service); no function here
// makes an authorization decision -- it relies on authHeaders() to attach
// the caller's own session token, same as every other data-layer file in
// this app. GET /api/agent/graphs/'s own view has no Depends(...)/
// login_required (services/agent_orchestrator/views.py's api_graphs), but
// that's not the whole picture: omnibioai-workbench registers a plugin's
// AuthenticationMiddleware (plugins/multi_agent_bio_orchestrator/
// middleware.py) globally, and its path guard actually matches every
// /api/* route project-wide (not just its own plugin's mount, despite that
// file's own comment) -- confirmed live, this endpoint 401s with no token.
// So a real Authorization header is required in practice; routes_agent_
// orchestrator_proxy.py already forwards it unconditionally.
//
// Field shapes mirror agent_orchestrator's own list_graphs() dict
// projection field-for-field (graphs/registry.py): graph_id, display_name,
// description, version, enabled, inputs_schema, dag. There is no
// "builder"/"architecture kind" field in that projection (builder_key is
// resolved server-side but dropped before the API response) -- the
// fixed-pipeline / ReAct agent / composite grouping AgenticAIPage.tsx
// renders is therefore a display-only classification this file computes
// from display_name text (classifyArchitecture below), not a field the
// upstream API returns. It's disclosed as a heuristic, not presented as
// upstream metadata.
//
// api_graphs() always calls list_graphs(include_disabled=False) -- there
// is no query parameter to ask for disabled graphs too, so a graph_id
// with "enabled": false in definitions.json is simply absent from this
// response, never returned with enabled: false. Every row this file can
// ever see is therefore enabled: true; that's a real, current limitation
// of the upstream endpoint, not something this page is hiding.
//
// There is no list-all-runs endpoint anywhere in agent_orchestrator (only
// POST ops/agent/run/ to start one, GET .../status/{run_id} once you
// already have a run_id) -- so there is no fetchAgentRuns() here. That
// absence is surfaced directly in AgenticAIPage.tsx's Run History tab as
// an explicit "not yet connected" state, not silently omitted.
import { authHeaders, reportUnauthorized } from './auth'

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

// ── Shapes ──────────────────────────────────────────────────────────────

export interface AgentGraphNode {
  id: string
  label?: string
  plugin?: string
  kind?: string
  [key: string]: unknown
}

export interface AgentGraphEdge {
  from: string
  to: string
}

export interface AgentGraphDag {
  nodes: AgentGraphNode[]
  edges: AgentGraphEdge[]
}

export interface AgentGraph {
  graph_id: string
  display_name: string
  description: string
  version: string
  enabled: boolean
  inputs_schema: Record<string, unknown>
  dag: AgentGraphDag | null
}

export type ArchitectureKind = 'react_agent' | 'composite' | 'fixed_pipeline'

// Display-only classification, computed client-side from display_name --
// see this file's own module comment for why there's no upstream field to
// read this from instead. "(ReAct)" is display_name's own, consistently
// applied suffix for every hand-authored ReAct graph in definitions.json
// (confirmed by reading that file directly: refdb_react_agent,
// drug_target_intelligence_agent, gene_function_mechanism_agent,
// structural_context_agent, clinical_trials_lookup_agent,
// pathway_mechanism_agent, pharmacogenomics_agent, hpo_phenotype_agent all
// carry it); "composite" likewise appears verbatim in the two graphs built
// specifically as a composite of other agents (drug_discovery_composite_
// agent, single_cell_annotation_composite_agent). Everything else --
// hand-authored fixed DAGs and generic_plan_executor-backed graphs alike
// -- is grouped as "fixed_pipeline": from the outside, both execute a
// predetermined node sequence rather than an LLM-driven action loop, which
// is the real distinction this grouping is trying to draw.
export function classifyArchitecture(graph: Pick<AgentGraph, 'display_name' | 'description'>): ArchitectureKind {
  const text = `${graph.display_name} ${graph.description}`.toLowerCase()
  if (text.includes('(react)') || text.includes('react agent')) return 'react_agent'
  if (text.includes('composite')) return 'composite'
  return 'fixed_pipeline'
}

export const ARCHITECTURE_LABEL: Record<ArchitectureKind, string> = {
  react_agent: 'ReAct Agents',
  composite: 'Composite Agents',
  fixed_pipeline: 'Fixed Pipelines',
}

export async function fetchAgentGraphs(): Promise<AgentGraph[]> {
  const path = '/agent-orchestrator/graphs'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  const data = await r.json()
  // omnibioai-workbench's api_graphs() wraps the array as {"graphs": [...]}
  // (views.py) -- unwrapped here so callers get the same flat array shape
  // every other fetch* in this app returns.
  const graphs = data?.graphs
  return Array.isArray(graphs) ? graphs : []
}

// -- same convention tes.ts's/model_registry.ts's own _errorMessage established.
const CLASSIFIABLE_STATUSES = [401, 403]

async function _errorMessage(r: Response, path: string): Promise<string> {
  try {
    const data = await r.json()
    const detail = typeof data?.detail === 'string' ? data.detail
      : typeof data?.error === 'string' ? data.error
      : null
    if (detail !== null) {
      return CLASSIFIABLE_STATUSES.includes(r.status) ? `${detail} ${r.status}` : detail
    }
  } catch {
    // fall through to the generic message below
  }
  return `${path} ${r.status}`
}
