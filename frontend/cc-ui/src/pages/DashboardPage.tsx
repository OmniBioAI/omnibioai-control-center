import { useEffect, useState } from 'react'
import {
  Activity, Bot, Building2, ClipboardList, Database, GitBranch, Receipt,
  ScrollText, ServerCog, Users,
} from 'lucide-react'
import { fetchSummary } from '../api'
import type { SummaryResponse } from '../api'
import { hasAdminAccess, hasPlatformAdminAccess } from '../auth'
import { fetchPlatformOrgs } from '../organizations'
import { fetchPlatformUsers } from '../users'
import { PageContainer, SectionHeader, StatCard } from '../components/ui'

/**
 * Admin Console Phase 2: the new Overview landing page. Organizations,
 * Users, and Platform Health cards fetch real data through the exact
 * same existing, already-tested endpoints the Organizations/Users/
 * Health pages themselves use (fetchPlatformOrgs/fetchPlatformUsers/
 * fetchSummary) -- gated by the same permission checks, so a viewer
 * without platform-admin or ops access simply sees "—" rather than a
 * doomed-to-403 request or fabricated data.
 *
 * AI Models, Running Workflows, TES Jobs, Knowledge Base, and Billing
 * have no live API in this repo yet (per this phase's explicit
 * non-goals) -- their cards are clearly marked `placeholder` (renders a
 * "Preview data" tag, see StatCard.tsx) so nothing here could be
 * mistaken for a working integration.
 */
export default function DashboardPage() {
  const [orgCount, setOrgCount] = useState<number | null>(null)
  const [userCount, setUserCount] = useState<number | null>(null)
  const [summary, setSummary] = useState<SummaryResponse | null>(null)

  useEffect(() => {
    if (!hasPlatformAdminAccess()) return
    fetchPlatformOrgs({ pageSize: 1 }).then(r => setOrgCount(r.total)).catch(() => {})
    fetchPlatformUsers({ pageSize: 1 }).then(r => setUserCount(r.total)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!hasAdminAccess()) return
    fetchSummary().then(setSummary).catch(() => {})
  }, [])

  const healthAccent = summary?.overall_status === 'DOWN' ? 'red' : summary?.overall_status === 'WARN' ? 'amber' : 'green'

  return (
    <PageContainer>
      <SectionHeader title="Overview" description="Platform-wide status across the OmniBioAI enterprise console." />
      <div
        className="shell-stat-grid"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}
      >
        <StatCard label="Organizations" value={orgCount ?? '—'} icon={Building2} />
        <StatCard label="Users" value={userCount ?? '—'} icon={Users} />
        <StatCard
          label="Platform Health"
          value={summary?.overall_status ?? '—'}
          icon={Activity}
          accent={summary ? healthAccent : 'default'}
        />
        <StatCard label="Services" value={summary?.services?.length ?? '—'} icon={ServerCog} />
        <StatCard label="AI Models" value={4} icon={Bot} placeholder />
        <StatCard label="Running Workflows" value={2} icon={GitBranch} placeholder />
        <StatCard label="TES Jobs" value={7} icon={ClipboardList} placeholder />
        <StatCard label="Knowledge Base" value="128 docs" icon={Database} placeholder />
        <StatCard label="Billing" value="—" icon={Receipt} placeholder />
        <StatCard label="Audit" value="—" icon={ScrollText} placeholder />
      </div>
    </PageContainer>
  )
}
