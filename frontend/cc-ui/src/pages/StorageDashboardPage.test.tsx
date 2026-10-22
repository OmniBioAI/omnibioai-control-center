import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StorageOverview } from '../api'
import StorageDashboardPage from './StorageDashboardPage'

const fetchStorageOverview = vi.fn()
vi.mock('../api', () => ({ fetchStorageOverview: (...args: unknown[]) => fetchStorageOverview(...args) }))

const observedAt = '2026-10-20T12:00:00Z'
const sample: StorageOverview = {
  schema_version: '1.0', observed_at: observedAt, freshness: 'CURRENT', readiness_state: 'NOT_VERIFIED',
  sources: { restic: { status: 'UNAVAILABLE', observed_at: observedAt, detail: 'Credentials not configured' } },
  physical_devices: [{
    role: 'primary', label: 'Primary', device_identity: '6a805bb7-2513-435f-9cd4-b9970a0e4fc4', filesystem_uuid: '6a805bb7-2513-435f-9cd4-b9970a0e4fc4', filesystem: 'ext4', read_only: false,
    mount_point: '/mnt/primary', mount_status: 'MOUNTED', mount_mode: 'READ_WRITE', total_bytes: 1000,
    used_bytes: 400, available_bytes: 600, utilization_percent: 40, mount_options: ['rw'], transport: null,
    transport_topology: null,
    smart_status: 'UNAVAILABLE', health: 'UNKNOWN', health_detail: 'SMART unavailable', aggregate: false,
    last_observed_error: null, last_successful_observation: observedAt, operational_state: null, note: null,
  }],
  archive_pool: {
    pool_mount_point: '/mnt/archive', pool_status: 'MOUNTED', total_bytes: 3000, used_bytes: 1200,
    available_bytes: 1800, utilization_percent: 40, create_policy: 'ff', min_free_bytes: null,
    min_free_policy_status: 'NOT_CONFIGURED', dependencies: ['/mnt/branch-a'], dependency_assessment: 'CONFIGURED',
    configured_source: '/etc/fstab', dependency_note: 'Not verified', runtime_policy_status: 'NOT_VERIFIED',
    branches: [{ mount_point: '/mnt/branch-a', role: 'archive-a', expected_mode: 'READ_ONLY', observed_mode: 'READ_ONLY', mount_status: 'MOUNTED', filesystem: 'ext4', filesystem_uuid: 'uuid-a', total_bytes: 2000, available_bytes: 500 }],
  },
  backups: {
    repository_status: 'AVAILABLE', repository_id: null, snapshot_count: 1, snapshots_truncated: false,
    snapshots: [{ id: 'abc12345', time: observedAt, age_seconds: 0, source_paths: ['…/dataset'], tags: ['daily'] }],
    latest_snapshot_at: observedAt, schedule_status: 'UNKNOWN', schedules: [], retention_status: 'UNKNOWN',
    retention_summary: null, restore_verification: 'NOT_VERIFIED', observed_at: observedAt, detail: 'Inventory read only',
  },
  alerts: [{ id: 'pool-missing', state: 'ACTIVE', severity: 'WARNING', affected_device: 'archive', source: 'mountinfo', observed_at: observedAt, evidence: 'Branch missing', suggested_action: 'Check member' }],
  readiness_gates: [{ id: 'restore', label: 'Isolated restore', state: 'NOT_VERIFIED', evidence_source: 'Restore record', observed_at: observedAt, explanation: 'No restore evidence.' }],
}

describe('StorageDashboardPage', () => {
  beforeEach(() => { fetchStorageOverview.mockReset(); fetchStorageOverview.mockResolvedValue(sample) })

  it('shows live observation states and does not add aggregate archive branches to physical capacity', async () => {
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Storage & Backup')).toBeTruthy()
    expect(screen.getByText('Primary')).toBeTruthy()
    expect(screen.getByText(/600 B available/)).toBeTruthy()
  })

  it('renders all six views using typed observations', async () => {
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getByText('UUID 6a805bb7-2513-435f-9cd4-b9970a0e4fc4')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Archive Pool' }))
    expect(screen.getByText('Create policy')).toBeTruthy()
    expect(screen.getByText('ff')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Backups & Snapshots' }))
    expect(screen.getByText('abc12345')).toBeTruthy()
    expect(screen.getByText('…/dataset')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Health & Alerts' }))
    expect(screen.getByText('Branch missing')).toBeTruthy()
    expect(screen.getByText('Warning')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Recovery & Readiness' }))
    expect(screen.getByText('No restore evidence.')).toBeTruthy()
    expect(screen.getAllByText('Not verified').length).toBeGreaterThan(0)
    expect(screen.queryByText('NOT_VERIFIED')).toBeNull()
  })

  it('surfaces unavailable telemetry and retry on backend errors', async () => {
    fetchStorageOverview.mockRejectedValueOnce(new Error('/storage/overview 503'))
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Storage telemetry is unavailable.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(fetchStorageOverview).toHaveBeenCalledTimes(2))
  })

  it('shows one no-data reason and marks stale snapshots', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      freshness: 'STALE',
      physical_devices: [{
        ...sample.physical_devices[0], total_bytes: null, used_bytes: null, available_bytes: null,
        utilization_percent: null, health_detail: 'No data: snapshot file is missing',
      }],
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText('No data: snapshot file is missing')).toBeTruthy()
    expect(screen.queryByText(/No data: No data/)).toBeNull()
    expect(screen.getByText(/Last updated .+ \(stale\)/)).toBeTruthy()
    expect(screen.queryByText(/Unavailable used/)).toBeNull()
  })

  it('renders being replaced as a neutral note', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      physical_devices: [{ ...sample.physical_devices[0], operational_state: 'being_replaced', note: 'This target is being replaced.' }],
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText('This target is being replaced.')).toBeTruthy()
  })

  it('shows a sleeping disk as a neutral Standby', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      physical_devices: [{
        ...sample.physical_devices[0], power_state: 'STANDBY', health: 'UNKNOWN',
        health_detail: 'Standby: SMART skipped so the disk is not woken',
      }],
    })
    render(<StorageDashboardPage />)
    const badges = await screen.findAllByText('Standby')
    expect(badges.length).toBeGreaterThan(0)
    expect(screen.getByText('Standby: SMART skipped so the disk is not woken')).toBeTruthy()
    expect(screen.queryByText('UNKNOWN')).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getAllByText('Standby').length).toBeGreaterThan(0)
  })

  it('shows Not mounted without a no-data prefix', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      physical_devices: [{
        ...sample.physical_devices[0], mount_status: 'MISSING', total_bytes: null, used_bytes: null,
        available_bytes: null, utilization_percent: null, health_detail: 'Not mounted',
      }],
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Not mounted')).toBeTruthy()
    expect(screen.queryByText(/No data: Not mounted/)).toBeNull()
  })

  const device = sample.physical_devices[0]
  const member = (role: string, label: string, readOnly: boolean, used: number, total: number) => ({
    ...device, role, label, read_only: readOnly, pool_role: 'archive-pool', mount_point: `/mnt/${role}`,
    mount_mode: readOnly ? 'READ_ONLY' as const : 'READ_WRITE' as const, health: 'HEALTHY' as const,
    total_bytes: total, used_bytes: used, available_bytes: total - used, utilization_percent: Math.round((used / total) * 1000) / 10,
    health_detail: readOnly ? 'Read-only; capacity is shown without warnings' : 'Capacity collected with statvfs from the read-only bind mount',
  })
  const TiB = 1024 ** 4
  const withPool: StorageOverview = {
    ...sample,
    alerts: [],
    physical_devices: [
      { ...device, smart_passed: true, smart_attributes: { '5': 0, '197': 0, '198': 0, '199': 1234 }, temperature_celsius: 34, health: 'HEALTHY' },
      member('archive', 'Archive', false, 2.2 * TiB, 20 * TiB),
      member('data2tb', 'OmniBioAI data 2 TB', true, 1.746 * TiB, 1.8 * TiB),
      member('archive2tb-b', 'Archive 2 TB B', true, 1.786 * TiB, 1.9 * TiB),
    ],
    archive_pool: {
      ...sample.archive_pool, pool_mount_point: '/mnt/omnibioai-archive', total_bytes: 23.7 * TiB, used_bytes: 5.73 * TiB,
      available_bytes: 17.97 * TiB, pool_detail: 'mergerfs pool verified by filesystem type and branch list', branches: [],
    },
  }

  it('shows the archive pool total with its member disks, read-only disks neutral', async () => {
    fetchStorageOverview.mockResolvedValueOnce(withPool)
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Archive pool')).toBeTruthy()
    expect(screen.getByText('23.7 TiB')).toBeTruthy()
    expect(screen.getByText('5.73 TiB used · 18.0 TiB free')).toBeTruthy()
    for (const label of ['Archive', 'OmniBioAI data 2 TB', 'Archive 2 TB B']) expect(screen.getByLabelText(`${label} pool member`)).toBeTruthy()
    expect(screen.getAllByText('read-only')).toHaveLength(2)
    const fill = (label: string) => (screen.getAllByLabelText(`${label} utilization`)[0].firstChild as HTMLElement).style.background
    expect(fill('OmniBioAI data 2 TB')).toBe('var(--muted)')
    expect(fill('Archive')).toBe('var(--accent)')
    expect(screen.queryByText(/WARNING|Warning|CRITICAL/)).toBeNull()
  })

  it('lists the pool and its members on Devices & Volumes with collected SMART evidence', async () => {
    fetchStorageOverview.mockResolvedValueOnce(withPool)
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getByText('mergerfs · 0 member disks')).toBeTruthy()
    expect(screen.getByText('↳ OmniBioAI data 2 TB')).toBeTruthy()
    expect(screen.getAllByText('Read-only')).toHaveLength(2)
    expect(screen.getAllByText('read-only view').length).toBe(4)
    expect(screen.getByText('SMART passed')).toBeTruthy()
    expect(screen.getByText('5: 0 · 197: 0 · 198: 0 · 199: 1,234')).toBeTruthy()
    expect(screen.getByText('34 °C')).toBeTruthy()
    expect(screen.queryByText(/Transport:/)).toBeNull()
    expect(screen.queryByText(/Last observed error/)).toBeNull()
    expect(screen.queryByText('READ_ONLY')).toBeNull()
    expect(screen.getAllByText('Mounted').length).toBeGreaterThan(0)
  })

  it('shows NVMe wear, media errors and temperature', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      physical_devices: [{ ...device, smart_passed: true, nvme_percentage_used: 3, nvme_media_errors: 0, temperature_celsius: 41 }],
    })
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getByText('Wear 3% · media errors 0')).toBeTruthy()
    expect(screen.getByText('41 °C')).toBeTruthy()
  })

  it('shows a disk being replaced as a neutral Replacing badge, never Missing', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      alerts: [],
      physical_devices: [{
        ...device, operational_state: 'being_replaced', note: 'This target is being replaced.', mount_status: 'MISSING',
        total_bytes: null, used_bytes: null, available_bytes: null, utilization_percent: null, health_detail: 'Not mounted',
      }],
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Replacing')).toBeTruthy()
    expect(screen.queryByText(/MISSING/i)).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getAllByText('Replacing')).toHaveLength(2)
    expect(screen.queryByText(/MISSING/i)).toBeNull()
  })

  it('summarises the latest snapshot with human-readable size and file count', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...sample,
      backups: { ...sample.backups, snapshot_count: 12345, latest_snapshot_file_count: 75_600_000, latest_snapshot_size_bytes: 3089592662016 },
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Latest snapshot: 75.6M files · 2.81 TiB')).toBeTruthy()
    expect(screen.getByText('12,345 snapshots observed')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Backups & Snapshots' }))
    expect(screen.getByText('Latest snapshot: 75.6M files · 2.81 TiB')).toBeTruthy()
    expect(screen.getByText('Snapshots: 12,345')).toBeTruthy()
  })

  it('omits the latest snapshot line when the repository has no summary', async () => {
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    expect(screen.queryByText(/Latest snapshot:/)).toBeNull()
  })

  it('uses real tabs with arrow-key, Home and End navigation and no page-level Refresh', async () => {
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull()
    expect(screen.getByText(/^Last updated /)).toBeTruthy()
    expect(screen.queryByText(/Storage 1.0 readiness/)).toBeNull()
    const tablist = screen.getByRole('tablist', { name: 'Storage dashboard views' })
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map(tab => tab.textContent)).toEqual(['Overview', 'Devices & Volumes', 'Archive Pool', 'Backups & Snapshots', 'Health & Alerts', 'Recovery & Readiness'])
    expect(tabs.map(tab => tab.tabIndex)).toEqual([0, -1, -1, -1, -1, -1])
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe('storage-tab-overview')

    fireEvent.keyDown(tablist, { key: 'ArrowRight' })
    const devices = screen.getByRole('tab', { name: 'Devices & Volumes' })
    expect(devices.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(devices)
    expect(devices.tabIndex).toBe(0)
    expect(screen.getByRole('heading', { name: 'Devices & Volumes' })).toBeTruthy()

    fireEvent.keyDown(tablist, { key: 'End' })
    expect(screen.getByRole('tab', { name: 'Recovery & Readiness' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(tablist, { key: 'ArrowRight' })  // wraps to the first tab
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(tablist, { key: 'ArrowLeft' })   // wraps to the last tab
    expect(screen.getByRole('tab', { name: 'Recovery & Readiness' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(tablist, { key: 'Home' })
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(tablist, { key: 'Enter' })       // other keys change nothing
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true')
  })

  it('shows the mergerfs pool, its settings and each branch with size, use and SMART', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...withPool,
      archive_pool: {
        ...withPool.archive_pool, create_policy: 'ff', min_free_bytes: 4294967295, mergerfs_version: '2.33.5', unreadable_settings: [],
        utilization_percent: 24.2, pool_detail: null, runtime_policy_status: 'NOT_VERIFIED', dependency_assessment: 'NOT_VERIFIED',
        branches: withPool.physical_devices.slice(1).map(device => ({
          mount_point: device.mount_point, role: device.role, label: device.label, read_only: device.read_only,
          expected_mode: device.read_only ? 'READ_ONLY' as const : 'READ_WRITE' as const,
          observed_mode: device.read_only ? 'READ_ONLY' as const : 'READ_WRITE' as const,
          mount_status: 'MOUNTED' as const, filesystem: 'ext4', filesystem_uuid: null, total_bytes: device.total_bytes,
          used_bytes: device.used_bytes, available_bytes: device.available_bytes, utilization_percent: device.utilization_percent, health: 'HEALTHY' as const,
        })),
      },
      physical_devices: withPool.physical_devices.map(device => device.role === 'data2tb'
        ? { ...device, smart_passed: true, smart_attributes: { '5': 0, '197': 0, '198': 0, '199': 0 }, temperature_celsius: 31 } : device),
    })
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Archive Pool' }))
    expect(screen.getByText('/mnt/omnibioai-archive')).toBeTruthy()
    expect(screen.getByText('23.7 TiB')).toBeTruthy()
    expect(screen.getByText('5.73 TiB')).toBeTruthy()
    expect(screen.getByText('4.00 GiB')).toBeTruthy()
    expect(screen.getByText('2.33.5')).toBeTruthy()
    expect(screen.getByText('Read-write')).toBeTruthy()
    expect(screen.getAllByText('read-only')).toHaveLength(2)
    expect(screen.getByText(/· 97%/)).toBeTruthy()
    expect(screen.getByText('31 °C')).toBeTruthy()
    expect(screen.getAllByText('No SMART data')).toHaveLength(2)
    const archive = within(screen.getByRole('region', { name: 'Archive pool details' }))
    for (const gone of [/NOT_VERIFIED/, /Not verified/, /policy evidence/i, /dependency/i, /Couldn't read/]) expect(archive.queryByText(gone)).toBeNull()
  })

  it("names each unreadable mergerfs setting once", async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...withPool,
      archive_pool: { ...withPool.archive_pool, create_policy: null, min_free_bytes: null, mergerfs_version: '2.33.5', unreadable_settings: ['create policy', 'minimum free space'] },
    })
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Archive Pool' }))
    expect(screen.getAllByText("Couldn't read create policy")).toHaveLength(1)
    expect(screen.getAllByText("Couldn't read minimum free space")).toHaveLength(1)
    expect(screen.queryByText('Create policy')).toBeNull()
    expect(screen.getByText('2.33.5')).toBeTruthy()
  })

  const basicDisk = (overrides: Partial<StorageOverview['physical_devices'][number]> = {}) => ({
    ...member('data2tb', 'OmniBioAI data 2 TB', true, 1.746 * TiB, 1.8 * TiB),
    smart_mode: 'scsi_health_only' as const, power_state: 'UNKNOWN' as const, smart_passed: true, smart_attributes: {},
    smart_status: 'AVAILABLE' as const, smart_checked_at: '2026-10-22T06:00:00Z', ...overrides,
  })
  const BASIC = 'Health OK (basic, enclosure limits SMART)'

  it('shows enclosure-limited disks as neutral basic health, never missing or standby', async () => {
    fetchStorageOverview.mockResolvedValueOnce({ ...withPool, physical_devices: [withPool.physical_devices[0], basicDisk()] })
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    const badge = screen.getByText(BASIC)
    expect(badge.style.color).toBe('var(--muted)')
    expect(badge.style.textTransform).toBe('none')
    expect(screen.getAllByText(BASIC)).toHaveLength(1)                      // the badge, not repeated below it
    const row = within(screen.getByText('↳ OmniBioAI data 2 TB').closest('tr') as HTMLElement)
    expect(row.getByText(/^Checked .+ · every 6 hours$/)).toBeTruthy()
    for (const wrong of [/Standby/, /Not mounted/, /MISSING/i, /SMART passed/, /SMART unavailable/]) expect(row.queryByText(wrong)).toBeNull()
  })

  it('shows basic health in the Archive Pool SMART column and on a writable disk card', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...withPool,
      physical_devices: [basicDisk({ role: 'archive', label: 'Archive', read_only: false, pool_role: null })],
      archive_pool: { ...withPool.archive_pool, branches: [{
        mount_point: '/mnt/data2tb', role: 'archive', label: 'Archive', read_only: false, expected_mode: 'READ_WRITE', observed_mode: 'READ_WRITE',
        mount_status: 'MOUNTED', filesystem: 'ext4', filesystem_uuid: null, total_bytes: 100, used_bytes: 10, available_bytes: 90, utilization_percent: 10, health: 'HEALTHY',
      }] },
    })
    render(<StorageDashboardPage />)
    expect(await screen.findByText(BASIC)).toBeTruthy()                     // overview card badge
    expect(screen.queryByText('Healthy')).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Archive Pool' }))
    expect(screen.getByText(BASIC)).toBeTruthy()
  })

  it('shows a failed basic health check as a warning', async () => {
    fetchStorageOverview.mockResolvedValueOnce({
      ...withPool, physical_devices: [basicDisk({ smart_passed: false, health: 'WARNING', health_detail: 'Basic SMART health check failed' })],
    })
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getByText('Warning')).toBeTruthy()
    expect(screen.getByText('Basic health check failed')).toBeTruthy()
    expect(screen.queryByText(BASIC)).toBeNull()
  })
})

