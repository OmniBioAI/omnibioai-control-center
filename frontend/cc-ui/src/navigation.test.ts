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

describe('navigation: Security Posture placement', () => {
  it('is one functional, permission-gated top-level Security item after Overview', () => {
    const securitySection = NAVIGATION.find(section => section.key === 'security')!
    const posture = securitySection.items.find(item => item.key === 'security-posture')
    expect(posture).toBeDefined()
    expect(posture!.functional).toBe(true)
    expect(posture!.visible).toBeDefined()
    expect(posture!.children).toBeUndefined()
    expect(securitySection.items.indexOf(posture!)).toBe(
      securitySection.items.findIndex(item => item.key === 'security-overview') + 1,
    )
  })
})

// PR-B5-B (Control Center Interaction Admin View). Same reasoning as the
// Sessions block above.

describe('navigation: Interactions placement', () => {
  it('has exactly one "interactions" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'interactions') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'interactions') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places "interactions" under the Security section, functional and gated', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')
    expect(securitySection).toBeDefined()

    const interactionsItem = securitySection!.items.find(i => i.key === 'interactions')
    expect(interactionsItem).toBeDefined()
    expect(interactionsItem!.functional).toBe(true)
    // Same gate audit-logs uses -- GET /platform/interactions is
    // manage_all_orgs-gated, not org-scoped or self-service.
    expect(interactionsItem!.visible).toBeDefined()
  })

  it('is a top-level Security item alongside Audit Logs, not nested under it', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    const interactionsItem = securitySection.items.find(i => i.key === 'interactions')!
    expect(interactionsItem.children).toBeUndefined()
  })
})

// HIPAA Basic Compliance Report v0.8.0. Same reasoning as the
// Sessions/Interactions blocks above.

describe('navigation: Compliance Report placement', () => {
  it('has exactly one "compliance-report" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'compliance-report') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'compliance-report') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places "compliance-report" under the Security section, functional and gated', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')
    expect(securitySection).toBeDefined()

    const complianceItem = securitySection!.items.find(i => i.key === 'compliance-report')
    expect(complianceItem).toBeDefined()
    expect(complianceItem!.functional).toBe(true)
    // Same gate audit-logs uses -- GET /compliance/hipaa-report is
    // manage_all_orgs-gated, not org-scoped.
    expect(complianceItem!.visible).toBeDefined()
  })

  it('is a top-level Security item alongside Audit Logs, not nested under it', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    const complianceItem = securitySection.items.find(i => i.key === 'compliance-report')!
    expect(complianceItem.children).toBeUndefined()
  })
})

// PR9 (SAML Admin UI). Same reasoning as the Sessions/Interactions/
// Compliance Report blocks above.

describe('navigation: SAML Settings placement', () => {
  it('has exactly one "saml" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'saml') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'saml') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places "saml" under the Security section, functional and gated the same way as "iam"/"mfa-policy"', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')
    expect(securitySection).toBeDefined()

    const samlItem = securitySection!.items.find(i => i.key === 'saml')
    const iamItem = securitySection!.items.find(i => i.key === 'iam')
    expect(samlItem).toBeDefined()
    expect(samlItem!.functional).toBe(true)
    // manage_sso is org-scoped -- same hasOrganizationsAccess gate 'iam'
    // (OIDC SSO) already uses, since PR8/auth#49 deliberately reused
    // manage_sso for SAML rather than a new manage_saml permission.
    expect(samlItem!.visible).toBe(iamItem!.visible)
  })

  it('is a top-level Security item alongside IAM / SSO Management, not nested under it', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    const samlItem = securitySection.items.find(i => i.key === 'saml')!
    expect(samlItem.children).toBeUndefined()
  })
})

// PR-B6. Same reasoning as the Sessions/Interactions blocks above.

describe('navigation: Integrations placement', () => {
  it('has exactly one "integrations" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'integrations') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'integrations') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places "integrations" under the Platform section, functional and hasAdminAccess-gated', () => {
    const platformSection = NAVIGATION.find(s => s.key === 'platform')
    expect(platformSection).toBeDefined()

    const integrationsItem = platformSection!.items.find(i => i.key === 'integrations')
    expect(integrationsItem).toBeDefined()
    expect(integrationsItem!.functional).toBe(true)
    // Same gate 'cloud'/'settings' use -- GET /integrations requires no
    // permission at all upstream (see routes_integrations.py), so this
    // gate is the only real access control this page has.
    expect(integrationsItem!.visible).toBeDefined()
  })

  it('is a top-level Platform item alongside Settings, not nested under it', () => {
    const platformSection = NAVIGATION.find(s => s.key === 'platform')!
    const integrationsItem = platformSection.items.find(i => i.key === 'integrations')!
    expect(integrationsItem.children).toBeUndefined()
  })

  it('no longer renders as Coming Soon', () => {
    const platformSection = NAVIGATION.find(s => s.key === 'platform')!
    const integrationsItem = platformSection.items.find(i => i.key === 'integrations')!
    expect(integrationsItem.functional).not.toBe(false)
  })
})

// Admin Console HIPAA Compliance Report (V1): "Admin Console > Compliance
// > HIPAA Compliance" -- a dedicated Compliance section, deliberately
// distinct from the pre-existing 'compliance-report' item under
// Security (a different feature: HIPAA Basic Compliance Report v0.8.0,
// an org-scoped usage/access-log export -- see this item's own comment
// in navigation.ts).

describe('navigation: HIPAA Compliance placement', () => {
  it('has exactly one "hipaa-compliance" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'hipaa-compliance') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'hipaa-compliance') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('lives in its own dedicated "Compliance" section, not nested under Security', () => {
    const complianceSection = NAVIGATION.find(s => s.key === 'compliance')
    expect(complianceSection).toBeDefined()
    expect(complianceSection!.label).toBe('Compliance')

    const item = complianceSection!.items.find(i => i.key === 'hipaa-compliance')
    expect(item).toBeDefined()
    expect(item!.label).toBe('HIPAA Compliance')
    expect(item!.functional).toBe(true)
    expect(item!.children).toBeUndefined()

    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    expect(securitySection.items.some(i => i.key === 'hipaa-compliance')).toBe(false)
  })

  it('is a distinct entry from the pre-existing "compliance-report" item', () => {
    const securitySection = NAVIGATION.find(s => s.key === 'security')!
    const legacyReportItem = securitySection.items.find(i => i.key === 'compliance-report')
    expect(legacyReportItem).toBeDefined()
    expect(legacyReportItem!.key).not.toBe('hipaa-compliance')
  })

  it('is gated (not always-visible like "sessions"/"overview")', () => {
    const complianceSection = NAVIGATION.find(s => s.key === 'compliance')!
    const item = complianceSection.items.find(i => i.key === 'hipaa-compliance')!
    expect(item.visible).toBeDefined()
  })
})

describe('navigation: Regression Health placement', () => {
  it('places Regression Health after Health', () => {
    const operations = NAVIGATION.find(section => section.key === 'operations')!
    const infrastructure = operations.items.find(item => item.key === 'infrastructure')!
    expect(infrastructure.children?.map(item => item.key)).toEqual(
      expect.arrayContaining(['health', 'regression-health'])
    )
    const keys = infrastructure.children!.map(item => item.key)
    expect(keys.indexOf('regression-health')).toBe(keys.indexOf('health') + 1)
  })

  it('is functional and gated by the existing platform.manage_infra permission', () => {
    const operations = NAVIGATION.find(section => section.key === 'operations')!
    const infrastructure = operations.items.find(item => item.key === 'infrastructure')!
    const item = infrastructure.children!.find(child => child.key === 'regression-health')!
    expect(item.label).toBe('Regression Health')
    expect(item.functional).toBe(true)
    expect(item.visible).toBeDefined()
  })
})

// DH-3: Deployment Health, immediately after Regression Health and
// before Docker -- the DH-3 task brief's explicit ordering. This
// supersedes Regression Health's own "before Docker" assertion above
// (which now has Deployment Health in between); that block above only
// asserts "after Health" for exactly this reason -- the full
// Health -> Regression Health -> Deployment Health -> Docker chain is
// asserted once, here, rather than in two places that could drift.

describe('navigation: Deployment Health placement', () => {
  it('has exactly one "deployment-health" entry across the entire tree', () => {
    const found: { sectionKey: string; parentKey?: string }[] = []
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.key === 'deployment-health') found.push({ sectionKey: section.key })
        for (const child of item.children ?? []) {
          if (child.key === 'deployment-health') found.push({ sectionKey: section.key, parentKey: item.key })
        }
      }
    }
    expect(found).toHaveLength(1)
  })

  it('places the full chain Health -> Regression Health -> Deployment Health -> Integration Health -> Docker in order', () => {
    const operations = NAVIGATION.find(section => section.key === 'operations')!
    const infrastructure = operations.items.find(item => item.key === 'infrastructure')!
    const keys = infrastructure.children!.map(item => item.key)
    expect(keys.indexOf('regression-health')).toBe(keys.indexOf('health') + 1)
    expect(keys.indexOf('deployment-health')).toBe(keys.indexOf('regression-health') + 1)
    expect(keys.indexOf('integration-health')).toBe(keys.indexOf('deployment-health') + 1)
    expect(keys.indexOf('docker')).toBe(keys.indexOf('integration-health') + 1)
  })

  it('is functional and uses the same platform.manage_infra gate', () => {
    const operations = NAVIGATION.find(section => section.key === 'operations')!
    const infrastructure = operations.items.find(item => item.key === 'infrastructure')!
    const item = infrastructure.children!.find(child => child.key === 'integration-health')!
    const regressionItem = infrastructure.children!.find(child => child.key === 'regression-health')!
    expect(item.label).toBe('Integration Health')
    expect(item.functional).toBe(true)
    expect(item.visible).toBe(regressionItem.visible)
  })

  it('is functional and gated by the existing platform.manage_infra permission (same as Regression Health)', () => {
    const operations = NAVIGATION.find(section => section.key === 'operations')!
    const infrastructure = operations.items.find(item => item.key === 'infrastructure')!
    const item = infrastructure.children!.find(child => child.key === 'deployment-health')!
    const regressionItem = infrastructure.children!.find(child => child.key === 'regression-health')!
    expect(item.label).toBe('Deployment Health')
    expect(item.functional).toBe(true)
    expect(item.visible).toBeDefined()
    expect(item.visible).toBe(regressionItem.visible)
  })
})
