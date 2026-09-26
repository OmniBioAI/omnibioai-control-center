import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { hasPlatformAdminAccess } from '../../auth'
import { NAVIGATION, isNavItemVisible, type PageKey } from '../../navigation'
import { fetchPlatformOrgs } from '../../organizations'
import { fetchPlatformUsers } from '../../users'

export type RecordKind = 'user' | 'org'
interface RecordHit { kind: RecordKind; id: number; label: string; detail: string }
type Result = { type: 'page'; entry: Entry } | { type: 'record'; hit: RecordHit }

interface Entry { key: PageKey; label: string; section: string }

/** Every page the current session can open, from the same NAVIGATION
 * tree (and the same visibility gates) the sidebar renders. */
export function searchablePages(): Entry[] {
  const out: Entry[] = []
  for (const section of NAVIGATION) {
    for (const item of section.items.filter(isNavItemVisible)) {
      const sectionLabel = section.label || 'Home'
      if (item.children?.length) {
        for (const child of item.children.filter(isNavItemVisible)) {
          out.push({ key: child.key, label: child.label, section: `${sectionLabel} › ${item.label}` })
        }
      } else {
        out.push({ key: item.key, label: item.label, section: sectionLabel })
      }
    }
  }
  return out
}

/** Pages whose name matches first (prefix before substring), then pages
 * whose section matches -- "security" finds every Security page. */
export function matchPages(entries: Entry[], query: string): Entry[] {
  const q = query.trim().toLowerCase()
  if (!q) return entries
  const score = (e: Entry) => {
    const label = e.label.toLowerCase()
    if (label.startsWith(q)) return 0
    if (label.split(/[\s/&-]+/).some(w => w.startsWith(q))) return 1
    if (label.includes(q)) return 2
    if (e.section.toLowerCase().includes(q)) return 3
    return -1
  }
  return entries
    .map(e => [score(e), e] as const)
    .filter(([s]) => s >= 0)
    .sort((a, b) => a[0] - b[0])
    .map(([, e]) => e)
}

/** Organizations and users whose name/email match, from the same
 * /platform/orgs and /platform/users search the Organizations and Users
 * pages use. Platform admins only -- both endpoints are
 * manage_all_orgs-gated. A failing source just contributes no rows. */
export async function searchRecords(query: string): Promise<RecordHit[]> {
  const [orgs, users] = await Promise.all([
    fetchPlatformOrgs({ search: query, pageSize: 5, sortBy: 'name', sortOrder: 'asc' }).catch(() => null),
    fetchPlatformUsers({ search: query, pageSize: 5, sortBy: 'email', sortOrder: 'asc' }).catch(() => null),
  ])
  return [
    ...(orgs?.items ?? []).map(o => ({ kind: 'org' as const, id: o.id, label: o.name, detail: `Organization · ${o.member_count} members` })),
    ...(users?.items ?? []).map(u => ({ kind: 'user' as const, id: u.id, label: u.email, detail: `User · ${u.status}` })),
  ]
}

const RECORD_MIN_CHARS = 2
const RECORD_DEBOUNCE_MS = 250

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

/**
 * Admin Console global search: jump to any page by name, and (for
 * platform admins) to an organization or user by name/email. A compact
 * trigger in the top bar (so it doesn't squeeze the breadcrumb) opens a
 * panel with a live-filtered list; Ctrl+K / Cmd+K opens it from anywhere,
 * arrow keys move, Enter opens, Esc closes.
 */
export default function GlobalSearch({ onNavigate, onOpenRecord }: {
  onNavigate: (key: PageKey) => void
  /** Opens a user's or organization's detail page. Without it, only pages are searched. */
  onOpenRecord?: (kind: RecordKind, id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Recomputed per open so visibility follows the current session.
  const entries = useMemo(() => (open ? searchablePages() : []), [open])
  const [records, setRecords] = useState<RecordHit[]>([])
  const [recordsLoading, setRecordsLoading] = useState(false)
  const canSearchRecords = open && !!onOpenRecord && hasPlatformAdminAccess()

  useEffect(() => {
    const q = query.trim()
    if (!canSearchRecords || q.length < RECORD_MIN_CHARS) { setRecords([]); setRecordsLoading(false); return }
    let cancelled = false
    setRecordsLoading(true)
    const timer = setTimeout(() => {
      searchRecords(q).then(hits => {
        if (!cancelled) { setRecords(hits); setRecordsLoading(false) }
      })
    }, RECORD_DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query, canSearchRecords])

  const results: Result[] = useMemo(() => [
    ...matchPages(entries, query).map(entry => ({ type: 'page' as const, entry })),
    ...records.map(hit => ({ type: 'record' as const, hit })),
  ], [entries, query, records])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(o => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    inputRef.current?.focus()
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const go = (result: Result | undefined) => {
    if (!result) return
    if (result.type === 'page') onNavigate(result.entry.key)
    else onOpenRecord?.(result.hit.kind, result.hit.id)
    setOpen(false)
  }
  const resultId = (r: Result) => r.type === 'page' ? `global-search-${r.entry.key}` : `global-search-${r.hit.kind}-${r.hit.id}`

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIndex(i => Math.min(i + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIndex(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(results[index]) }
    else if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
  }

  return (
    <div ref={rootRef} className="shell-topbar-search" style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          padding: '6px 10px', background: 'var(--bg2)', color: 'var(--muted)', fontSize: 12, cursor: 'pointer',
        }}
      >
        <Search size={14} />
        <span>Search</span>
        <kbd style={{ fontSize: 10, padding: '1px 5px', border: '1px solid var(--border)', borderRadius: 4, fontFamily: 'var(--mono)' }}>
          {isMac ? '⌘K' : 'Ctrl K'}
        </kbd>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Search pages"
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', right: 0, width: 380, zIndex: 50,
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            boxShadow: '0 12px 32px rgba(0,0,0,0.35)', overflow: 'hidden',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
            <Search size={14} color="var(--muted)" />
            <input
              ref={inputRef}
              value={query}
              onChange={e => { setQuery(e.target.value); setIndex(0) }}
              onKeyDown={onInputKey}
              placeholder={onOpenRecord && hasPlatformAdminAccess() ? 'Pages, organizations, users…' : 'Go to page…'}
              aria-label="Search pages"
              role="combobox"
              aria-expanded
              aria-controls="global-search-results"
              aria-activedescendant={results[index] ? resultId(results[index]) : undefined}
              style={{ flex: 1, border: 'none', outline: 'none', background: 'transparent', color: 'var(--text)', fontSize: 13 }}
            />
          </div>
          <ul id="global-search-results" role="listbox" style={{ listStyle: 'none', maxHeight: 360, overflowY: 'auto', padding: 4 }}>
            {results.length === 0 && !recordsLoading && (
              <li style={{ padding: '12px 10px', fontSize: 12, color: 'var(--muted)' }}>Nothing matches “{query}”.</li>
            )}
            {results.map((r, i) => {
              const first = i === 0 || results[i - 1].type !== r.type
              return (
                <li key={resultId(r)} role="presentation">
                  {first && (
                    <div style={{ padding: '8px 10px 4px', fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--muted)' }}>
                      {r.type === 'page' ? 'Pages' : 'Organizations & users'}
                    </div>
                  )}
                  <div
                    id={resultId(r)}
                    role="option"
                    aria-selected={i === index}
                    onMouseEnter={() => setIndex(i)}
                    onMouseDown={e => { e.preventDefault(); go(r) }}
                    style={{
                      display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 10px', borderRadius: 6,
                      cursor: 'pointer', fontSize: 13,
                      background: i === index ? 'var(--accent-dim, rgba(0,212,170,0.1))' : 'transparent',
                      color: i === index ? 'var(--text)' : 'var(--text2)',
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.type === 'page' ? r.entry.label : r.hit.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{r.type === 'page' ? r.entry.section : r.hit.detail}</span>
                  </div>
                </li>
              )
            })}
            {recordsLoading && (
              <li style={{ padding: '8px 10px', fontSize: 11, color: 'var(--muted)' }}>Searching organizations and users…</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
