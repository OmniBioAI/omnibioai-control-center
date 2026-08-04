import { Construction } from 'lucide-react'
import EmptyState from './EmptyState'
import PageContainer from './PageContainer'
import SectionHeader from './SectionHeader'

/** Admin Console Phase 2 design system: the destination every
 * not-yet-implemented nav item (Workflows, AI Models, IAM, Audit Logs,
 * Billing, ...) renders. Explicitly out of scope per this PR to build
 * any of those modules -- this is what stands in for them until each
 * gets its own PR. Never fetches anything, never claims to be real
 * data. */
export default function ComingSoon({ title }: { title: string }) {
  return (
    <PageContainer>
      <SectionHeader title={title} />
      <EmptyState
        icon={Construction}
        title="Coming soon"
        description={`${title} isn't built yet. This section is reserved in the navigation for a future phase.`}
      />
    </PageContainer>
  )
}
