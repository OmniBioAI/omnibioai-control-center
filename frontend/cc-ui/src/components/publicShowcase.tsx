import { useEffect, useState, type ReactNode } from 'react'
import { Card, SectionHeader } from './ui'

// Shared building blocks for the anonymous control.omnibioai.org pages
// (PublicOverviewPage, PublicEvidencePage): per-section loading, honest
// "unavailable"/"coming soon" states, and the tile/section chrome.

export type Load<T> = { state: 'loading' } | { state: 'ok'; data: T } | { state: 'error' }

export function useLoad<T>(fn: () => Promise<T>, refreshKey: number): Load<T> {
  const [value, setValue] = useState<Load<T>>({ state: 'loading' })
  useEffect(() => {
    let cancelled = false
    setValue({ state: 'loading' })
    fn().then(
      data => { if (!cancelled) setValue({ state: 'ok', data }) },
      () => { if (!cancelled) setValue({ state: 'error' }) },
    )
    return () => { cancelled = true }
    // fn is a module-level fetcher; only refreshKey should re-trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])
  return value
}

export const fmt = (n: number | null | undefined) => (typeof n === 'number' ? n.toLocaleString('en-US') : '—')

export function daysAgo(iso: string | null): string {
  if (!iso) return ''
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`
}

export function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section style={{ marginTop: 32 }}>
      <SectionHeader title={title} description={description} />
      <div style={{ marginTop: 14 }}>{children}</div>
    </section>
  )
}

export function Grid({ min = 150, children }: { min?: number; children: ReactNode }) {
  // 150px keeps two tiles per row on a phone and five or six on a desktop.
  return <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`, gap: 12 }}>{children}</div>
}

export function Tile({ label, value, note, href }: { label: string; value: string; note?: string; href?: string }) {
  const body = (
    <Card style={{ height: '100%' }}>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--accent)', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginTop: 8 }}>{label}</div>
      {note && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.45 }}>{note}</div>}
    </Card>
  )
  return href
    ? <a href={href} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>{body}</a>
    : body
}

export function Unavailable({ what }: { what: string }) {
  return <Card><span style={{ fontSize: 13, color: 'var(--muted)' }}>{what} is unavailable right now.</span></Card>
}

export function Loading() {
  return <Card><span style={{ fontSize: 13, color: 'var(--muted)' }}>Loading…</span></Card>
}

export function Badge({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontFamily: 'var(--mono)', padding: '2px 7px', borderRadius: 4,
      margin: '0 4px 4px 0',
      color: ok ? 'var(--green)' : 'var(--muted)',
      background: ok ? 'var(--green-bg)' : 'transparent',
      border: `1px solid ${ok ? 'var(--green-border)' : 'var(--border)'}`,
    }}>{children}</span>
  )
}

export function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)', textDecoration: 'none' }}>{children}</a>
}
