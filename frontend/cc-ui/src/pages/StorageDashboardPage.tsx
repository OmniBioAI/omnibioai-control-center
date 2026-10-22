import { useCallback, useEffect, useState } from 'react'
import {
  fetchStorageOverview,
  type StorageAlert,
  type StorageDevice,
  type StorageOverview,
} from '../api'
import { classifyAuthError } from '../format'
import StatusBadge from '../components/StatusBadge'
import { Card, DataTable, EmptyState, ErrorState, LoadingState, SectionHeader } from '../components/ui'

type ViewKey = 'overview' | 'devices' | 'archive' | 'backups' | 'health' | 'readiness'
const VIEWS: { key: ViewKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'devices', label: 'Devices & Volumes' },
  { key: 'archive', label: 'Archive Pool' },
  { key: 'backups', label: 'Backups & Snapshots' },
  { key: 'health', label: 'Health & Alerts' },
  { key: 'readiness', label: 'Recovery & Readiness' },
]

function bytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable'
  if (value === 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** power).toFixed(power > 1 ? 1 : 0)} ${units[power]}`
}

function date(value?: string | null): string {
  if (!value) return 'Not recorded'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function validOverview(value: unknown): value is StorageOverview {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<StorageOverview>
  return data.schema_version === '1.0' && typeof data.observed_at === 'string'
    && Array.isArray(data.physical_devices) && !!data.archive_pool && !!data.backups
    && Array.isArray(data.alerts) && Array.isArray(data.readiness_gates) && !!data.sources
}

function CapacityCard({ device }: { device: StorageDevice }) {
  const utilization = device.utilization_percent
  const hasCapacity = device.total_bytes != null && device.used_bytes != null && device.available_bytes != null
  const status = device.health !== 'UNKNOWN' ? device.health : device.mount_status
  return (
    <Card style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{device.label}</div>
          {hasCapacity && <div style={{ fontSize: 19, fontWeight: 700, color: 'var(--text)', marginTop: 5 }}>{bytes(device.total_bytes)}</div>}
        </div>
        <StatusBadge status={status} />
      </div>
      {!hasCapacity ? <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 14 }}>{device.health_detail}</div> : <>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 14 }}>{bytes(device.used_bytes)} used · {bytes(device.available_bytes)} available</div>
        <div aria-label={`${device.label} utilization`} style={{ height: 7, marginTop: 9, borderRadius: 5, background: 'var(--bg3)', overflow: 'hidden' }}>
          {utilization != null && <div style={{ width: `${Math.max(0, Math.min(100, utilization))}%`, height: '100%', background: device.health === 'CRITICAL' ? 'var(--red)' : device.health === 'WARNING' ? 'var(--amber)' : 'var(--accent)' }} />}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 11, color: 'var(--muted)' }}><span>{utilization}% used</span><span>{device.mount_mode.replace('_', ' ')}</span></div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>{device.health_detail}</div>
      </>}
      {device.note && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text2)' }}>{device.note}</div>}
    </Card>
  )
}

function DeviceTable({ devices }: { devices: StorageDevice[] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable rows={devices} rowKey={device => device.role} emptyLabel="No device observations are available" columns={[
    { key: 'device', header: 'Device', render: row => <><strong>{row.label}</strong><div style={{ color: 'var(--muted)', fontSize: 11 }}>{row.device_identity ?? 'Identity unavailable'}</div></> },
    { key: 'uuid', header: 'Filesystem UUID', render: row => <code>{row.filesystem_uuid ?? 'Unavailable'}</code> },
    { key: 'filesystem', header: 'Filesystem', render: row => row.filesystem ?? 'Unavailable' },
    { key: 'mount', header: 'Mount', render: row => <><code>{row.mount_point}</code><div><StatusBadge status={row.mount_status} /> <StatusBadge status={row.mount_mode} /></div></> },
    { key: 'capacity', header: 'Capacity / Available', render: row => <>{bytes(row.total_bytes)}<div style={{ color: 'var(--muted)', fontSize: 11 }}>{bytes(row.available_bytes)} available</div></> },
    { key: 'health', header: 'Health', render: row => <><StatusBadge status={row.health} /><div style={{ color: 'var(--muted)', fontSize: 11 }}>{row.smart_status === 'UNAVAILABLE' ? 'SMART unavailable' : row.health_detail}</div><div style={{ color: 'var(--muted)', fontSize: 10 }}>Transport: {row.transport ?? 'Unknown'}{row.transport_topology ? ` · ${row.transport_topology}` : ''}</div><div style={{ color: 'var(--muted)', fontSize: 10 }}>Last observed error: {row.last_observed_error ?? 'None available'} · Last successful observation: {date(row.last_successful_observation)}</div></> },
  ]} /></div>
}

function AlertList({ alerts }: { alerts: StorageAlert[] }) {
  if (!alerts.length) return <EmptyState title="No current alerts reported" />
  return <div style={{ display: 'grid', gap: 10 }}>{alerts.map(alert => <Card key={alert.id} style={{ padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <StatusBadge status={alert.severity} />
      <strong style={{ color: 'var(--text)' }}>{alert.affected_device ?? 'Storage system'}</strong>
      <span style={{ color: 'var(--muted)', fontSize: 11 }}>{date(alert.observed_at)}</span>
    </div>
    <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 10 }}>{alert.evidence}</div>
    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>Action: {alert.suggested_action}</div>
    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 5 }}>Source: {alert.source}</div>
  </Card>)}</div>
}

export default function StorageDashboardPage() {
  const [view, setView] = useState<ViewKey>('overview')
  const [data, setData] = useState<StorageOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response: unknown = await fetchStorageOverview()
      if (!validOverview(response)) throw new Error('Invalid Storage telemetry response')
      setData(response)
      setError(null)
    } catch (reason) {
      setData(null)
      const message = String(reason)
      const auth = classifyAuthError(message)
      setError(auth === 'session' ? 'Your admin session has expired.' : auth === 'denied' ? 'You are not authorized to view infrastructure storage.' : 'Storage telemetry is unavailable.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  return <div>
    <SectionHeader title="Storage & Backup" description="Read-only infrastructure storage, archive, and recovery observations." />
    <div role="tablist" aria-label="Storage dashboard views" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 18 }}>
      {VIEWS.map(item => <button key={item.key} type="button" role="tab" aria-selected={view === item.key} onClick={() => setView(item.key)} className="shell-action-button">{item.label}</button>)}
      <button type="button" onClick={() => void load()} className="shell-action-button" style={{ marginLeft: 'auto' }}>Refresh</button>
    </div>
    {loading ? <LoadingState label="Loading storage observations…" /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : !data ? <EmptyState title="Storage telemetry unavailable" /> : <>
      <Card style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16, padding: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ fontSize: 12, color: 'var(--text2)' }}>Last updated {date(data.observed_at)}{data.freshness === 'STALE' ? ' (stale)' : ''}</span><StatusBadge status={data.freshness} /></div>
        <div style={{ fontSize: 12, color: 'var(--text2)' }}>Storage 1.0 readiness: {data.readiness_state}</div>
      </Card>
      {view === 'overview' && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 230px), 1fr))', gap: 12, marginBottom: 18 }}>
          {data.physical_devices.map(device => <CapacityCard key={device.role} device={device} />)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 14 }}>
          <Card><h3 style={{ marginTop: 0, fontSize: 14 }}>Backup inventory</h3><StatusBadge status={data.backups.repository_status} />{data.backups.repository_status === 'UNAVAILABLE' ? <p style={{ color: 'var(--muted)', fontSize: 12 }}>{data.backups.detail}</p> : <><p style={{ color: 'var(--text2)', fontSize: 12 }}>{data.backups.snapshot_count} snapshots observed</p><div style={{ fontSize: 12, color: 'var(--muted)' }}>Latest: {date(data.backups.latest_snapshot_at)}</div>{data.backups.retention_summary && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>Repository stats: {data.backups.retention_summary}</div>}<div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{data.backups.detail}</div></>}</Card>
          <Card><h3 style={{ marginTop: 0, fontSize: 14 }}>Active alerts</h3><AlertList alerts={data.alerts.filter(alert => alert.state === 'ACTIVE').slice(0, 3)} /></Card>
        </div>
      </>}
      {view === 'devices' && <><h2 style={{ fontSize: 15, color: 'var(--text)' }}>Devices & Volumes</h2><p style={{ color: 'var(--muted)', fontSize: 12 }}>Filesystem UUIDs are used when visible. Kernel device names and enclosure serials are not treated as durable identity.</p><DeviceTable devices={data.physical_devices} /></>}
      {view === 'archive' && <>
        <Card style={{ marginBottom: 14 }}><div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}><div><h2 style={{ margin: 0, fontSize: 15 }}>Archive pool</h2><code>{data.archive_pool.pool_mount_point}</code></div><StatusBadge status={data.archive_pool.pool_status} /></div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 12, marginTop: 14 }}><span>Create policy: <strong>{data.archive_pool.create_policy ?? 'Unknown'}</strong></span><span>Minimum free space: <strong>{data.archive_pool.min_free_bytes == null ? 'Not configured / unavailable' : bytes(data.archive_pool.min_free_bytes)}</strong></span><span>Runtime policy: {data.archive_pool.runtime_policy_status}</span></div>
          <p style={{ color: 'var(--muted)', fontSize: 11 }}>Configured from {data.archive_pool.configured_source}. This is configured policy evidence; effective runtime policy is not verified.</p>
          <div style={{ fontSize: 12, color: data.archive_pool.dependency_assessment === 'WARNING' ? 'var(--amber)' : 'var(--muted)' }}>Mount dependency assessment: {data.archive_pool.dependency_assessment}. {data.archive_pool.dependencies.length ? `Dependencies: ${data.archive_pool.dependencies.join(', ')}` : 'No dependency declarations observed.'} {data.archive_pool.dependency_note}</div>
        </Card>
        <div style={{ overflowX: 'auto' }}><DataTable rows={data.archive_pool.branches} rowKey={row => row.role} emptyLabel="No archive branches configured" columns={[
          { key: 'branch', header: 'Branch', render: row => <><strong>{row.role}</strong><div><code>{row.mount_point}</code></div></> },
          { key: 'fs', header: 'Filesystem / UUID', render: row => <>{row.filesystem ?? 'Unknown'}<div><code>{row.filesystem_uuid ?? 'UUID unavailable'}</code></div></> },
          { key: 'mode', header: 'Mode', render: row => <><StatusBadge status={row.expected_mode} /><div>Observed: <StatusBadge status={row.observed_mode} /></div></> },
          { key: 'state', header: 'Mount', render: row => <StatusBadge status={row.mount_status} /> },
          { key: 'capacity', header: 'Capacity / Free', render: row => <>{bytes(row.total_bytes)}<div style={{ color: 'var(--muted)' }}>{bytes(row.available_bytes)} free</div></> },
        ]} /></div>
      </>}
      {view === 'backups' && <>
        <Card style={{ marginBottom: 14 }}><div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}><h2 style={{ margin: 0, fontSize: 15 }}>Restic repository</h2><StatusBadge status={data.backups.repository_status} /></div><p style={{ fontSize: 12, color: 'var(--text2)' }}>{data.backups.detail}</p>{data.backups.retention_summary && <p style={{ fontSize: 12, color: 'var(--muted)' }}>Repository stats: {data.backups.retention_summary}</p>}<div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 12, color: 'var(--muted)' }}><span>Schedule: {data.backups.schedule_status}</span><span>Retention: {data.backups.retention_status}</span><span>Last restore verification: {data.backups.restore_verification}</span></div>{data.backups.schedules.map(item => <div key={item} style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>{item}</div>)}</Card>
        <div style={{ overflowX: 'auto' }}><DataTable rows={data.backups.snapshots} rowKey={row => row.id} emptyLabel="Snapshot inventory unavailable or empty" columns={[
          { key: 'id', header: 'Snapshot ID', render: row => <code>{row.id}</code> },
          { key: 'time', header: 'Time', render: row => date(row.time) },
          { key: 'age', header: 'Age', render: row => row.age_seconds == null ? 'Unknown' : `${Math.floor(row.age_seconds / 86400)} days` },
          { key: 'paths', header: 'Source paths (redacted)', render: row => row.source_paths.join(', ') || 'Unavailable' },
          { key: 'tags', header: 'Tags', render: row => row.tags.join(', ') || 'None' },
        ]} /></div>
      </>}
      {view === 'health' && <><h2 style={{ fontSize: 15, color: 'var(--text)' }}>Health & Alerts</h2><p style={{ color: 'var(--muted)', fontSize: 12 }}>Alerts combine the current capacity observation with the host SMART and filtered 24-hour kernel snapshot.</p><AlertList alerts={data.alerts} /></>}
      {view === 'readiness' && <>
        <Card style={{ marginBottom: 14 }}><h2 style={{ marginTop: 0, fontSize: 15 }}>Storage 1.0 recovery readiness</h2><StatusBadge status={data.readiness_state} /><p style={{ color: 'var(--muted)', fontSize: 12 }}>Production readiness remains unverified until every required gate has current evidence.</p></Card>
        <div style={{ display: 'grid', gap: 9 }}>{data.readiness_gates.map(gate => <Card key={gate.id} style={{ padding: 13 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}><strong style={{ fontSize: 12 }}>{gate.label}</strong><StatusBadge status={gate.state} /></div><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>{gate.explanation}</div><div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>Evidence: {gate.evidence_source} · Observed: {date(gate.observed_at)}</div></Card>)}</div>
      </>}
    </>}
  </div>
}

