import { describe, it, expect } from 'vitest'
import { NAVIGATION } from './navigation'

// PR-C (Control Center Sessions Integration). Direct assertions against
// the single source of truth navigation.ts's own NAVIGATION array --
// more precise than inferring placement from rendered DOM structure,
// and catches a future edit that moves/duplicates the entry even before
// any component test would.

describe('navigation: Sessions placement', () => {
  it('has exactly one "sessions" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'sessions') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'sessions') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places "sessions" under the Security section, not Health/Infrastructure/Operations', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')
    expect(securitySection).toBeDefined()

    const sessionsItem = securitySection!.items.find(i => i.key === 'sessions')
    expect(sessionsItem).toBeDefined()
    expect(sessionsItem!.functional).toBe(true)

    const operationsSection = NAVIGATION.find(s => s.key === 'operations')
    const infrastructure = operationsSection?.items.find(i => i.key === 'infrastructure')
    expect(infrastructure?.children?.some(c => c.key === 'sessions')).toBe(false)
  })

  it('is a top-level Security item alongside Audit Logs, not nested under it', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    const sessionsItem = securitySection.items.find(i => i.key === 'sessions')!
    const auditItem = securitySection.items.find(i => i.key === 'audit-logs')!
    expect(sessionsItem.children).toBeUndefined()
    expect(auditItem.children).toBeUndefined()
  })
})
