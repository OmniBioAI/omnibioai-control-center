import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
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

// Binary units with three significant figures: 2.81 TiB, 75.6 GiB, 123 GiB.
function bytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable'
  if (value < 1024) return `${num(value)} B`
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / 1024 ** power
  return `${scaled.toFixed(scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2)} ${units[power]}`
}

// Whole numbers always carry thousands separators.
function num(value: number): string {
  return value.toLocaleString('en-US')
}

// Large counts in compact form: 75.6M.
function compact(value: number): string {
  return value < 10000 ? num(value) : new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 3 }).format(value)
}

function percent(value: number): string {
  return `${value.toLocaleString('en-US', { maximumFractionDigits: 1 })}%`
}

function date(value?: string | null): string {
  if (!value) return 'Not recorded'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

const WORDS: Record<string, string> = {
  READ_ONLY: 'Read-only', READ_WRITE: 'Read-write', MISSING: 'Not mounted',
}

// API enum values as plain words: READ_ONLY -> "Read-only", NOT_VERIFIED -> "Not verified".
function words(value: string): string {
  return WORDS[value] ?? value.charAt(0).toUpperCase() + value.slice(1).toLowerCase().replace(/_/g, ' ')
}

// Colour comes from the enum value; the text is the plain word.
function Badge({ status }: { status: string }) {
  return <StatusBadge status={status} label={words(status)} />
}

function latestSnapshotSummary(backups: StorageOverview['backups']): string | null {
  const files = backups.latest_snapshot_file_count
  const size = backups.latest_snapshot_size_bytes
  if (files == null || size == null) return null
  return `Latest snapshot: ${compact(files)} files · ${bytes(size)}`
}

function validOverview(value: unknown): value is StorageOverview {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<StorageOverview>
  return data.schema_version === '1.0' && typeof data.observed_at === 'string'
    && Array.isArray(data.physical_devices) && !!data.archive_pool && !!data.backups
    && Array.isArray(data.alerts) && Array.isArray(data.readiness_gates) && !!data.sources
}

// A disk being replaced is a plan, not a fault; a sleeping disk is skipped, not faulty.
function deviceStatus(device: StorageDevice): string {
  if (device.operational_state === 'being_replaced') return 'replacing'
  if (device.power_state === 'STANDBY' && device.health === 'UNKNOWN') return 'standby'
  return device.health !== 'UNKNOWN' ? device.health : device.mount_status
}

function healthStatus(device: StorageDevice): string {
  if (device.operational_state === 'being_replaced') return 'replacing'
  return device.power_state === 'STANDBY' && device.health === 'UNKNOWN' ? 'standby' : device.health
}

function UsageBar({ label, value, tone }: { label: string; value: number | null; tone: string }) {
  return <div aria-label={`${label} utilization`} style={{ height: 7, marginTop: 9, borderRadius: 5, background: 'var(--bg3)', overflow: 'hidden' }}>
    {value != null && <div style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: '100%', background: tone }} />}
  </div>
}

// Read-only disks are full by design: their bar stays neutral and never turns amber or red.
function usageTone(health: string, readOnly: boolean): string {
  if (readOnly) return 'var(--muted)'
  return health === 'CRITICAL' ? 'var(--red)' : health === 'WARNING' ? 'var(--amber)' : 'var(--accent)'
}

function CapacityCard({ device }: { device: StorageDevice }) {
  const utilization = device.utilization_percent
  const hasCapacity = device.total_bytes != null && device.used_bytes != null && device.available_bytes != null
  return (
    <Card style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{device.label}</div>
          {hasCapacity && <div style={{ fontSize: 19, fontWeight: 700, color: 'var(--text)', marginTop: 5 }}>{bytes(device.total_bytes)}</div>}
        </div>
        <Badge status={deviceStatus(device)} />
      </div>
      {!hasCapacity ? device.health_detail !== words(deviceStatus(device)) && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 14 }}>{device.health_detail}</div> : <>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 14 }}>{bytes(device.used_bytes)} used · {bytes(device.available_bytes)} available</div>
        <UsageBar label={device.label} value={utilization} tone={usageTone(device.health, device.read_only)} />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 11, color: 'var(--muted)' }}><span>{utilization == null ? '' : `${percent(utilization)} used`}</span>{device.read_only ? <StatusBadge status="read-only" label="read-only" /> : <span>{words(device.mount_mode)}</span>}</div>
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>{device.health_detail}</div>
      </>}
      {device.note && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text2)' }}>{device.note}</div>}
    </Card>
  )
}

function PoolCard({ pool, members }: { pool: StorageOverview['archive_pool']; members: StorageDevice[] }) {
  const mounted = pool.total_bytes != null && pool.used_bytes != null && pool.available_bytes != null
  return <Card style={{ minWidth: 0, gridColumn: '1 / -1' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
      <div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Archive pool</div>
        {mounted && <div style={{ fontSize: 19, fontWeight: 700, color: 'var(--text)', marginTop: 5 }}>{bytes(pool.total_bytes)}</div>}
      </div>
      <Badge status={pool.pool_status} />
    </div>
    {mounted
      ? <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 14 }}>{bytes(pool.used_bytes)} used · {bytes(pool.available_bytes)} free</div>
      : <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 14 }}>{pool.pool_detail ?? 'Not mounted'}</div>}
    <div style={{ display: 'grid', gap: 10, marginTop: 14 }}>{members.map(device => <div key={device.role} aria-label={`${device.label} pool member`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, fontSize: 12 }}>
        <span style={{ color: 'var(--text)' }}>{device.label}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--muted)' }}>
          {device.total_bytes != null ? `${bytes(device.used_bytes)} of ${bytes(device.total_bytes)}` : device.health_detail}
          {device.read_only ? <StatusBadge status="read-only" label="read-only" /> : <Badge status={deviceStatus(device)} />}
        </span>
      </div>
      <UsageBar label={device.label} value={device.utilization_percent} tone={usageTone(device.health, device.read_only)} />
    </div>)}</div>
  </Card>
}

// Collected SMART evidence in plain words; nothing is shown when nothing was collected.
function smartLines(device: StorageDevice): string[] {
  if (device.power_state === 'STANDBY') return ['Standby: SMART skipped so the disk is not woken']
  const lines: string[] = []
  if (device.smart_passed != null) lines.push(device.smart_passed ? 'SMART passed' : 'SMART failed')
  const attributes = Object.entries(device.smart_attributes ?? {})
  if (attributes.length) lines.push(attributes.map(([id, value]) => `${id}: ${num(value)}`).join(' · '))
  const nvme = [
    device.nvme_percentage_used != null ? `Wear ${percent(device.nvme_percentage_used)}` : null,
    device.nvme_media_errors != null ? `media errors ${num(device.nvme_media_errors)}` : null,
  ].filter(Boolean)
  if (nvme.length) lines.push(nvme.join(' · '))
  if (device.temperature_celsius != null) lines.push(`${device.temperature_celsius} °C`)
  return lines
}

type DeviceRow = { kind: 'device'; device: StorageDevice; member: boolean } | { kind: 'pool'; pool: StorageOverview['archive_pool'] }

function deviceRows(devices: StorageDevice[], pool: StorageOverview['archive_pool']): DeviceRow[] {
  const members = devices.filter(device => device.pool_role)
  const rows: DeviceRow[] = devices.filter(device => !device.pool_role).map(device => ({ kind: 'device', device, member: false }))
  if (pool.pool_mount_point !== 'Not configured') rows.push({ kind: 'pool', pool })
  return rows.concat(members.map(device => ({ kind: 'device', device, member: true })))
}

const muted = { color: 'var(--muted)', fontSize: 11 }

function DeviceTable({ devices, pool }: { devices: StorageDevice[]; pool: StorageOverview['archive_pool'] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable<DeviceRow> rows={deviceRows(devices, pool)} rowKey={row => row.kind === 'pool' ? 'pool' : row.device.role} emptyLabel="No device observations are available" columns={[
    { key: 'device', header: 'Device', render: row => row.kind === 'pool'
      ? <><strong>Archive pool</strong><div style={muted}>mergerfs · {num(pool.branches.length)} member disks</div></>
      : <div style={{ paddingLeft: row.member ? 18 : 0 }}><strong>{row.member ? '↳ ' : ''}{row.device.label}</strong><div style={muted}>{row.device.device_identity ? `UUID ${row.device.device_identity}` : 'Identity not verified'}</div></div> },
    { key: 'filesystem', header: 'Filesystem', render: row => row.kind === 'pool' ? 'fuse.mergerfs' : row.device.filesystem ?? 'Unavailable' },
    { key: 'mount', header: 'Mount', render: row => row.kind === 'pool'
      ? <><code>{row.pool.pool_mount_point}</code><div><Badge status={row.pool.pool_status} /></div></>
      : <><code>{row.device.mount_point}</code><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 3 }}><Badge status={row.device.operational_state === 'being_replaced' ? 'replacing' : row.device.mount_status} />{row.device.mount_mode === 'READ_ONLY' && <StatusBadge status="read-only" label="Read-only" />}</div>{row.device.mount_status === 'MOUNTED' && <div style={muted}>read-only view</div>}</> },
    { key: 'capacity', header: 'Capacity / Available', render: row => {
      const item = row.kind === 'pool' ? row.pool : row.device
      return item.total_bytes == null ? <span style={muted}>Unavailable</span> : <>{bytes(item.total_bytes)}<div style={muted}>{bytes(item.available_bytes)} available</div></>
    } },
    { key: 'health', header: 'Health', render: row => {
      if (row.kind === 'pool') return <div style={muted}>{row.pool.pool_detail}</div>
      const device = row.device
      return <><Badge status={healthStatus(device)} /><div style={muted}>{device.health_detail}</div>{smartLines(device).map(line => <div key={line} style={muted}>{line}</div>)}{device.transport && <div style={{ ...muted, fontSize: 10 }}>Transport: {device.transport}{device.transport_topology ? ` · ${device.transport_topology}` : ''}</div>}{device.last_observed_error && device.last_observed_error !== device.health_detail && <div style={{ ...muted, fontSize: 10 }}>Last observed error: {device.last_observed_error}</div>}</>
    } },
  ]} /></div>
}

function AlertList({ alerts }: { alerts: StorageAlert[] }) {
  if (!alerts.length) return <EmptyState title="No current alerts reported" />
  return <div style={{ display: 'grid', gap: 10 }}>{alerts.map(alert => <Card key={alert.id} style={{ padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <Badge status={alert.severity} />
      <strong style={{ color: 'var(--text)' }}>{alert.affected_device ?? 'Storage system'}</strong>
      <span style={{ color: 'var(--muted)', fontSize: 11 }}>{date(alert.observed_at)}</span>
    </div>
    <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 10 }}>{alert.evidence}</div>
    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>Action: {alert.suggested_action}</div>
    <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 5 }}>Source: {alert.source}</div>
  </Card>)}</div>
}

// The mergerfs pool's own runtime settings; a setting that couldn't be read is said once, by name.
function ArchiveTab({ pool, devices }: { pool: StorageOverview['archive_pool']; devices: StorageDevice[] }) {
  const byRole = new Map(devices.map(device => [device.role, device]))
  const unreadable = new Set(pool.unreadable_settings ?? [])
  const mounted = pool.total_bytes != null
  const settings: [string, string, string | null][] = [
    ['create policy', 'Create policy', pool.create_policy],
    ['minimum free space', 'Minimum free space', pool.min_free_bytes == null ? null : bytes(pool.min_free_bytes)],
    ['mergerfs version', 'mergerfs', pool.mergerfs_version ?? null],
  ]
  return <section aria-label="Archive pool details">
    <Card style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div><h2 style={{ margin: 0, fontSize: 15 }}>Archive pool</h2><code>{pool.pool_mount_point}</code></div>
        <Badge status={pool.pool_status} />
      </div>
      {mounted ? <>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 14 }}>
          {([['Total', pool.total_bytes], ['Used', pool.used_bytes], ['Free', pool.available_bytes]] as const).map(([label, value]) =>
            <div key={label}><div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div><div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text)' }}>{bytes(value)}</div></div>)}
        </div>
        <UsageBar label="Archive pool" value={pool.utilization_percent} tone="var(--accent)" />
        <dl style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12, margin: '14px 0 0' }}>
          {settings.filter(([key, , value]) => value != null && !unreadable.has(key)).map(([key, label, value]) =>
            <div key={key}><dt style={{ color: 'var(--muted)', fontSize: 11 }}>{label}</dt><dd style={{ margin: 0, color: 'var(--text)' }}>{value}</dd></div>)}
        </dl>
        {[...unreadable].map(name => <div key={name} style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>Couldn't read {name}</div>)}
      </> : <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 12 }}>{pool.pool_detail ?? 'Not mounted'}</div>}
    </Card>
    <div style={{ overflowX: 'auto' }}><DataTable rows={pool.branches} rowKey={row => row.role} emptyLabel="No archive branches configured" columns={[
      { key: 'branch', header: 'Branch', render: row => <><strong>{row.label ?? row.role}</strong><div><code>{row.mount_point}</code></div></> },
      { key: 'mode', header: 'Mode', render: row => row.read_only ? <StatusBadge status="read-only" label="read-only" /> : <span>{words(row.observed_mode === 'UNKNOWN' ? row.expected_mode : row.observed_mode)}</span> },
      { key: 'size', header: 'Size', render: row => row.total_bytes == null ? <span style={muted}>{words(row.mount_status)}</span> : bytes(row.total_bytes) },
      { key: 'use', header: 'Use', render: row => row.used_bytes == null ? '' : <div style={{ minWidth: 140 }}>{bytes(row.used_bytes)}{row.utilization_percent != null && <span style={muted}> · {percent(row.utilization_percent)}</span>}<UsageBar label={`${row.label ?? row.role} branch`} value={row.utilization_percent ?? null} tone={usageTone(row.health ?? 'UNKNOWN', !!row.read_only)} /></div> },
      { key: 'smart', header: 'SMART', render: row => {
        const device = byRole.get(row.role)
        const lines = device ? smartLines(device) : []
        return lines.length ? lines.map(line => <div key={line} style={{ fontSize: 11 }}>{line}</div>) : <span style={muted}>No SMART data</span>
      } },
    ]} /></div>
  </section>
}

// Arrow keys, Home and End move between tabs (automatic activation); only the active tab is in the Tab order.
function StorageTabs({ view, onChange }: { view: ViewKey; onChange: (next: ViewKey) => void }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = VIEWS.findIndex(item => item.key === view)
    const target = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: VIEWS.length - 1 }[event.key]
    if (target === undefined) return
    event.preventDefault()
    const next = VIEWS[(target + VIEWS.length) % VIEWS.length].key
    onChange(next)
    refs.current[next]?.focus()
  }
  return <div role="tablist" aria-label="Storage dashboard views" className="storage-tabs" onKeyDown={onKeyDown}>
    {VIEWS.map(item => <button
      key={item.key} ref={node => { refs.current[item.key] = node }} type="button" role="tab"
      id={`storage-tab-${item.key}`} aria-selected={view === item.key} aria-controls="storage-panel"
      tabIndex={view === item.key ? 0 : -1} onClick={() => onChange(item.key)}
    >{item.label}</button>)}
  </div>
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
    <StorageTabs view={view} onChange={setView} />
    <div role="tabpanel" id="storage-panel" aria-labelledby={`storage-tab-${view}`}>
    {loading ? <LoadingState label="Loading storage observations…" /> : error ? <ErrorState message={error} onRetry={() => void load()} /> : !data ? <EmptyState title="Storage telemetry unavailable" /> : <>
      <Card style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16, padding: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ fontSize: 12, color: 'var(--text2)' }}>Last updated {date(data.observed_at)}{data.freshness === 'STALE' ? ' (stale)' : ''}</span><Badge status={data.freshness} /></div>
        <div style={{ fontSize: 12, color: 'var(--text2)' }}>Storage 1.0 readiness: {words(data.readiness_state)}</div>
      </Card>
      {view === 'overview' && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 230px), 1fr))', gap: 12, marginBottom: 18 }}>
          {data.physical_devices.filter(device => !device.pool_role).map(device => <CapacityCard key={device.role} device={device} />)}
          {data.archive_pool.pool_mount_point !== 'Not configured' && <PoolCard pool={data.archive_pool} members={data.physical_devices.filter(device => device.pool_role)} />}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 14 }}>
          <Card><h3 style={{ marginTop: 0, fontSize: 14 }}>Backup inventory</h3><Badge status={data.backups.repository_status} />{data.backups.repository_status === 'UNAVAILABLE' ? <p style={{ color: 'var(--muted)', fontSize: 12 }}>{data.backups.detail}</p> : <><p style={{ color: 'var(--text2)', fontSize: 12 }}>{num(data.backups.snapshot_count ?? 0)} snapshots observed</p><div style={{ fontSize: 12, color: 'var(--muted)' }}>Latest: {date(data.backups.latest_snapshot_at)}</div>{latestSnapshotSummary(data.backups) && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 6 }}>{latestSnapshotSummary(data.backups)}</div>}<div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{data.backups.detail}</div></>}</Card>
          <Card><h3 style={{ marginTop: 0, fontSize: 14 }}>Active alerts</h3><AlertList alerts={data.alerts.filter(alert => alert.state === 'ACTIVE').slice(0, 3)} /></Card>
        </div>
      </>}
      {view === 'devices' && <><h2 style={{ fontSize: 15, color: 'var(--text)' }}>Devices & Volumes</h2><p style={{ color: 'var(--muted)', fontSize: 12 }}>Filesystem UUIDs are used when visible. Kernel device names and enclosure serials are not treated as durable identity.</p><DeviceTable devices={data.physical_devices} pool={data.archive_pool} /></>}
      {view === 'archive' && <ArchiveTab pool={data.archive_pool} devices={data.physical_devices} />}
      {view === 'backups' && <>
        <Card style={{ marginBottom: 14 }}><div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}><h2 style={{ margin: 0, fontSize: 15 }}>Restic repository</h2><Badge status={data.backups.repository_status} /></div><p style={{ fontSize: 12, color: 'var(--text2)' }}>{data.backups.detail}</p>{latestSnapshotSummary(data.backups) && <p style={{ fontSize: 12, color: 'var(--text2)' }}>{latestSnapshotSummary(data.backups)}</p>}<div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 12, color: 'var(--muted)' }}><span>Snapshots: {data.backups.snapshot_count == null ? 'Unavailable' : num(data.backups.snapshot_count)}</span><span>Schedule: {words(data.backups.schedule_status)}</span><span>Retention: {words(data.backups.retention_status)}</span><span>Last restore verification: {words(data.backups.restore_verification)}</span></div>{data.backups.schedules.map(item => <div key={item} style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>{item}</div>)}</Card>
        <div style={{ overflowX: 'auto' }}><DataTable rows={data.backups.snapshots} rowKey={row => row.id} emptyLabel="Snapshot inventory unavailable or empty" columns={[
          { key: 'id', header: 'Snapshot ID', render: row => <code>{row.id}</code> },
          { key: 'time', header: 'Time', render: row => date(row.time) },
          { key: 'age', header: 'Age', render: row => row.age_seconds == null ? 'Unknown' : `${num(Math.floor(row.age_seconds / 86400))} days` },
          { key: 'paths', header: 'Source paths (redacted)', render: row => row.source_paths.join(', ') || 'Unavailable' },
          { key: 'tags', header: 'Tags', render: row => row.tags.join(', ') || 'None' },
        ]} /></div>
      </>}
      {view === 'health' && <><h2 style={{ fontSize: 15, color: 'var(--text)' }}>Health & Alerts</h2><p style={{ color: 'var(--muted)', fontSize: 12 }}>Alerts combine the current capacity observation with the host SMART and filtered 24-hour kernel snapshot.</p><AlertList alerts={data.alerts} /></>}
      {view === 'readiness' && <>
        <Card style={{ marginBottom: 14 }}><h2 style={{ marginTop: 0, fontSize: 15 }}>Storage 1.0 recovery readiness</h2><Badge status={data.readiness_state} /><p style={{ color: 'var(--muted)', fontSize: 12 }}>Production readiness remains unverified until every required gate has current evidence.</p></Card>
        <div style={{ display: 'grid', gap: 9 }}>{data.readiness_gates.map(gate => <Card key={gate.id} style={{ padding: 13 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}><strong style={{ fontSize: 12 }}>{gate.label}</strong><Badge status={gate.state} /></div><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>{gate.explanation}</div><div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>Evidence: {gate.evidence_source} · Observed: {date(gate.observed_at)}</div></Card>)}</div>
      </>}
    </>}
    </div>
  </div>
}

