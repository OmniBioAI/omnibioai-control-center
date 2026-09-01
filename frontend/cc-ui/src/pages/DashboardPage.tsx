import { useEffect, useState } from 'react'
import {
  Bot, BookOpen, BrainCircuit, Building2, Clock, Cpu, CreditCard,
  Database, FileText, FlaskConical, HardDrive, Layers, ListOrdered,
  MemoryStick, PlayCircle, Receipt, ServerCog, ShieldCheck, Users, UsersRound,
  Wallet, Workflow, XCircle,
} from 'lucide-react'
import { fetchDashboardSummary } from '../dashboard'
import type { DashboardSummary } from '../dashboard'
import { SectionHeader } from '../components/ui'
import { AlertCard, DashboardGrid, HealthCard, MetricCard, StatusCard } from '../components/dashboard'

function subscriptionTone(status: string | null): 'good' | 'bad' | 'neutral' {
  if (status === 'active' || status === 'trial') return 'good'
  if (status === 'suspended' || status === 'cancelled') return 'bad'
  return 'neutral'
}

/**
 * PR10: Live Platform Dashboard. Replaces Phase 2's single hardcoded
 * stat grid with one real backend call (GET /dashboard/summary, see
 * routes_dashboard.py) rendered through the reusable dashboard/
 * component family -- every section below is a <DashboardGrid> of
 * MetricCard/HealthCard/AlertCard/StatusCard, not a one-off layout, so a
 * future module (Billing, IAM, ...) extends this page by adding one more
 * section in the same shape rather than inventing new markup.
 *
 * Every field the backend couldn't get a live number for (see that
 * file's own docstring for the exact list -- Active Sessions, Embedding
 * Models, CPU/Memory, Uptime, all of Business) arrives as `null` and
 * renders as "--" here, never a fabricated placeholder number -- the
 * only cards marked `placeholder` (the amber "Preview data" tag) are
 * ones with NO possible live source at all, matching Phase 2's own
 * convention.
 */
function formatBytes(bytes: number | null): string | null {
  if (bytes == null) return null
  const tb = bytes / 1e12
  if (tb >= 1) return `${tb.toFixed(1)} TB`
  const gb = bytes / 1e9
  return `${gb.toFixed(1)} GB`
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetchDashboardSummary().then(setData).catch(() => setError(true))
  }, [])

  const identity = data?.identity
  const ai = data?.ai_platform
  const knowledge = data?.knowledge
  const workflow = data?.workflow
  const infra = data?.infrastructure
  const ops = data?.operations
  const business = data?.business

  return (
    <div>
      <SectionHeader title="Overview" description="Live status across the OmniBioAI enterprise platform." />

      {error && (
        <p style={{ fontSize: 12, color: 'var(--red)', marginBottom: 16 }}>
          Couldn't load the platform summary -- showing what's cached, if anything.
        </p>
      )}

      <DashboardGrid title="Identity" description="omnibioai-auth">
        <MetricCard label="Organizations" value={identity?.organizations ?? null} icon={Building2} />
        <MetricCard label="Users" value={identity?.users ?? null} icon={Users} />
        <MetricCard label="Teams" value={identity?.teams ?? null} icon={UsersRound} />
        <MetricCard label="Roles" value={identity?.roles ?? null} icon={ShieldCheck} />
        <MetricCard label="Active Sessions" value={identity?.active_sessions ?? null} icon={Clock} placeholder />
      </DashboardGrid>

      <DashboardGrid title="AI Platform" description="omnibioai-model-registry">
        <MetricCard label="Registered Models" value={ai?.registered_models ?? null} icon={Bot} />
        <MetricCard label="Active Models" value={ai?.active_models ?? null} icon={Bot} />
        <MetricCard label="Embedding Models" value={ai?.embedding_models ?? null} icon={Layers} placeholder />
        <MetricCard label="LLM Providers" value={ai?.llm_providers ?? null} icon={BrainCircuit} />
      </DashboardGrid>

      <DashboardGrid title="Knowledge Platform" description="omnibioai-rag">
        <MetricCard label="RAG Collections" value={knowledge?.rag_collections ?? null} icon={BookOpen} />
        <MetricCard label="Indexed Documents" value={knowledge?.indexed_documents ?? null} icon={FileText} />
        <MetricCard label="Indexed Publications" value={knowledge?.indexed_publications ?? null} icon={FlaskConical} />
        <MetricCard label="Knowledge Bases" value={knowledge?.knowledge_bases ?? null} icon={Database} />
      </DashboardGrid>

      <DashboardGrid title="Workflow Platform" description="omnibioai-workflow-bundles / omnibioai-tes">
        <MetricCard label="Workflow Bundles" value={workflow?.workflow_bundles ?? null} icon={Workflow} />
        <MetricCard label="Running Jobs" value={workflow?.running_jobs ?? null} icon={PlayCircle} />
        <MetricCard label="Queued Jobs" value={workflow?.queued_jobs ?? null} icon={ListOrdered} />
        <MetricCard label="Failed Jobs" value={workflow?.failed_jobs ?? null} icon={XCircle} />
      </DashboardGrid>

      <DashboardGrid title="Infrastructure" description="omnibioai-control-center">
        <MetricCard
          label="Containers"
          value={infra?.containers_running ?? null}
          icon={ServerCog}
          sublabel={infra?.containers_stopped != null ? `${infra.containers_stopped} stopped` : undefined}
        />
        <MetricCard
          label="Services"
          value={infra?.services_healthy != null ? `${infra.services_healthy}/${infra.services_total}` : null}
          icon={ServerCog}
        />
        <StatusCard
          label="GPU"
          statusText={infra?.gpu_utilization_pct != null ? `${infra.gpu_utilization_pct}% util` : null}
          tone={infra?.gpu_utilization_pct != null ? 'good' : 'neutral'}
          icon={Cpu}
        />
        <MetricCard
          label="Storage"
          value={formatBytes(infra?.storage_used_bytes ?? null)}
          icon={HardDrive}
          sublabel={infra ? `of ${formatBytes(infra.storage_total_bytes)}` : undefined}
        />
        <MetricCard label="CPU" value={infra?.cpu_pct != null ? `${infra.cpu_pct}%` : null} icon={Cpu} placeholder />
        <MetricCard label="Memory" value={infra?.memory_pct != null ? `${infra.memory_pct}%` : null} icon={MemoryStick} placeholder />
      </DashboardGrid>

      <DashboardGrid title="Operations">
        <HealthCard label="Health" status={ops?.health ?? null} />
        <AlertCard label="Alerts" count={ops?.alerts ?? null} />
        <MetricCard label="Active Services" value={ops?.active_services ?? null} icon={ServerCog} />
        <MetricCard label="Uptime" value={ops?.uptime ?? null} icon={Clock} placeholder />
      </DashboardGrid>

      <DashboardGrid title="Business" description="omnibioai-billing, your organization">
        <MetricCard label="Plan" value={business?.plan_name ?? null} icon={CreditCard} />
        <StatusCard
          label="Subscription"
          statusText={business?.subscription_status ?? null}
          tone={subscriptionTone(business?.subscription_status ?? null)}
          icon={Receipt}
        />
        <MetricCard label="Usage (services)" value={business?.usage_services_count ?? null} icon={Wallet} />
        <StatusCard
          label="Billing Service"
          statusText={business?.billing_service_available == null ? null : business.billing_service_available ? 'Available' : 'Unavailable'}
          tone={business?.billing_service_available == null ? 'neutral' : business.billing_service_available ? 'good' : 'bad'}
          icon={ServerCog}
        />
      </DashboardGrid>
    </div>
  )
}
