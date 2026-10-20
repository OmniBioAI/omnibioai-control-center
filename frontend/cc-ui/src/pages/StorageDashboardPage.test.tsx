import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    role: 'primary', label: 'Primary', device_identity: 'Model X', filesystem_uuid: 'uuid-1', filesystem: 'ext4',
    mount_point: '/mnt/primary', mount_status: 'MOUNTED', mount_mode: 'READ_WRITE', total_bytes: 1000,
    used_bytes: 400, available_bytes: 600, utilization_percent: 40, mount_options: ['rw'], transport: 'USB',
    transport_topology: '/sys/devices/usb1/1-1',
    smart_status: 'UNAVAILABLE', health: 'UNKNOWN', health_detail: 'SMART unavailable', aggregate: false,
    last_observed_error: null, last_successful_observation: observedAt,
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
    expect(screen.getByText('Archive pool (aggregate)')).toBeTruthy()
    expect(screen.getByText(/600 B available/)).toBeTruthy()
    expect(screen.getByText('Branches are shown separately and not added to this total.')).toBeTruthy()
  })

  it('renders all six views using typed observations', async () => {
    render(<StorageDashboardPage />)
    await screen.findByText('Storage & Backup')
    fireEvent.click(screen.getByRole('tab', { name: 'Devices & Volumes' }))
    expect(screen.getByText('uuid-1')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Archive Pool' }))
    expect(screen.getByText(/Runtime policy:/)).toBeTruthy()
    expect(screen.getByText('ff')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Backups & Snapshots' }))
    expect(screen.getByText('abc12345')).toBeTruthy()
    expect(screen.getByText('…/dataset')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Health & Alerts' }))
    expect(screen.getByText('Branch missing')).toBeTruthy()
    expect(screen.getByText('ACTIVE')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Recovery & Readiness' }))
    expect(screen.getByText('No restore evidence.')).toBeTruthy()
    expect(screen.getAllByText('NOT_VERIFIED').length).toBeGreaterThan(0)
  })

  it('surfaces unavailable telemetry and retry on backend errors', async () => {
    fetchStorageOverview.mockRejectedValueOnce(new Error('/storage/overview 503'))
    render(<StorageDashboardPage />)
    expect(await screen.findByText('Storage telemetry is unavailable.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(fetchStorageOverview).toHaveBeenCalledTimes(2))
  })
})
