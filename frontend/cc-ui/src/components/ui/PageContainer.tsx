import type { ReactNode } from 'react'

/**
 * Admin Console Phase 2 design system: groups a page's content. Padding
 * now comes from AppShell's <main>, which wraps every page, so this adds
 * none of its own -- it used to center content in a 1280px box, which
 * made the pages using it (ComingSoon) sit differently from every other
 * page.
 */
export default function PageContainer({ children }: { children: ReactNode }) {
  return <div>{children}</div>
}
