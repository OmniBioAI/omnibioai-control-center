import { beforeEach, describe, expect, it, vi } from 'vitest'
import { lookupLicenseIdentity } from './licenses'
import { fetchPlatformUserDetail, fetchPlatformUsers } from './users'

vi.mock('./auth', () => ({ authHeaders: () => ({}), reportUnauthorized: vi.fn() }))
vi.mock('./users', () => ({ fetchPlatformUsers: vi.fn(), fetchPlatformUserDetail: vi.fn() }))

const listUser = {
  id: 41,
  email: 'person@example.test',
  status: 'active',
  created_at: null,
  global_roles: [],
  org_count: 1,
  last_login_at: null,
  authentication_method: 'password',
  mfa_enabled: true,
}
const detail = {
  id: 41, email: 'person@example.test', status: 'active',
  memberships: [{ organization_id: 8, organization_name: 'Example', organization_slug: 'example', roles: ['org_member'], status: 'active', joined_at: null }],
}

beforeEach(() => {
  vi.mocked(fetchPlatformUsers).mockReset().mockResolvedValue({
    items: [listUser], total: 1, page: 1, page_size: 100, total_pages: 1,
  })
  vi.mocked(fetchPlatformUserDetail).mockReset().mockResolvedValue(detail as never)
})

describe('license identity eligibility lookup', () => {
  it('selects an exact active identity with active membership using existing read APIs', async () => {
    await expect(lookupLicenseIdentity(' PERSON@EXAMPLE.TEST ', 8)).resolves.toEqual({
      user_id: 41, email: 'person@example.test', organization_id: 8,
    })
    expect(fetchPlatformUsers).toHaveBeenCalledWith(expect.objectContaining({ search: 'person@example.test' }))
    expect(fetchPlatformUserDetail).toHaveBeenCalledWith(41)
  })

  it('does not match a partial email as an existing identity', async () => {
    vi.mocked(fetchPlatformUsers).mockResolvedValue({
      items: [{ ...listUser, email: 'person@example.test.attacker' }], total: 1, page: 1, page_size: 100, total_pages: 1,
    })
    await expect(lookupLicenseIdentity('person@example.test', 8)).rejects.toMatchObject({ code: 'identity_missing' })
    expect(fetchPlatformUserDetail).not.toHaveBeenCalled()
  })

  it('rejects inactive identities before membership lookup', async () => {
    vi.mocked(fetchPlatformUsers).mockResolvedValue({
      items: [{ ...listUser, status: 'suspended' }], total: 1, page: 1, page_size: 100, total_pages: 1,
    })
    await expect(lookupLicenseIdentity('person@example.test', 8)).rejects.toMatchObject({ code: 'identity_inactive' })
    expect(fetchPlatformUserDetail).not.toHaveBeenCalled()
  })

  it('rejects cross-tenant and unaccepted memberships', async () => {
    vi.mocked(fetchPlatformUserDetail).mockResolvedValue({
      ...detail,
      memberships: [{ ...detail.memberships[0], organization_id: 9 }],
    } as never)
    await expect(lookupLicenseIdentity('person@example.test', 8)).rejects.toMatchObject({ code: 'identity_membership_required' })

    vi.mocked(fetchPlatformUserDetail).mockResolvedValue({
      ...detail,
      memberships: [{ ...detail.memberships[0], status: 'invited' }],
    } as never)
    await expect(lookupLicenseIdentity('person@example.test', 8)).rejects.toMatchObject({ code: 'identity_membership_required' })
  })

  it('preserves server authorization failures instead of bypassing them', async () => {
    vi.mocked(fetchPlatformUsers).mockRejectedValue(new Error('/platform/users 403'))
    await expect(lookupLicenseIdentity('person@example.test', 8)).rejects.toThrow('/platform/users 403')
    expect(fetchPlatformUserDetail).not.toHaveBeenCalled()
  })
})
