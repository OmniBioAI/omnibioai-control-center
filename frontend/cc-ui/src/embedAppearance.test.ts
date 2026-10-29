import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { describe, expect, it } from 'vitest'
import {
  appearanceFromSearch,
  connectAppearanceMessages,
  EMBED_READY_EVENT,
  EMBED_THEME_EVENT,
  parseThemeMessage,
} from './embedAppearance'

const html = fs.readFileSync(path.resolve(process.cwd(), 'index.html'), 'utf8')
const bootstrap = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/)?.[1]

function embedded(referrer = 'https://webstudio.omnibioai.org/workbench') {
  const listeners = new Map<string, EventListener>()
  const sent: Array<[unknown, string]> = []
  const parent = { postMessage: (message: unknown, origin: string) => sent.push([message, origin]) }
  const win = {
    parent,
    addEventListener: (type: string, handler: EventListener) => listeners.set(type, handler),
    removeEventListener: (type: string) => listeners.delete(type),
  }
  const root = { dataset: {}, style: { cssText: 'untouched' }, innerHTML: 'untouched' }
  return {
    win: win as unknown as Window,
    doc: { referrer, documentElement: root } as unknown as Document,
    parent,
    root,
    listeners,
    sent,
  }
}

describe('embedded appearance protocol', () => {
  it('runs the bounded pre-paint bootstrap before styles and scrubs private parameters', () => {
    expect(bootstrap).toBeTruthy()
    expect(html.indexOf('<script>')).toBeLessThan(html.indexOf('<link'))
    const location = {
      pathname: '/_svc/control/',
      search: '?obai_theme=%3Csvg%3E&obai_accent=purple&obai_density=compact&obai_motion=reduce&obai_owner=x&token=x&author=Jane&username=reader',
      hash: '#go',
    }
    let replaced = ''
    const root = { dataset: {}, style: { cssText: 'untouched' }, innerHTML: 'untouched' }
    const windowObject = {
      location,
      matchMedia: () => ({ matches: false }),
      history: { state: null, replaceState: (_state: unknown, _title: string, url: string) => { replaced = url } },
    }
    Object.assign(windowObject, { parent: windowObject })
    vm.runInNewContext(bootstrap!, {
      window: windowObject,
      document: { documentElement: root },
      URLSearchParams,
      Object,
      Set,
      Array,
    })

    expect(root.dataset).toEqual({ theme: 'light', accent: 'purple', density: 'compact', motion: 'reduce', embedded: 'false' })
    const clean = new URL(replaced, 'https://control.example')
    expect(clean.searchParams.has('obai_owner')).toBe(false)
    expect(clean.searchParams.has('token')).toBe(false)
    expect(clean.searchParams.get('author')).toBe('Jane')
    expect(clean.searchParams.get('username')).toBe('reader')
    expect(clean.hash).toBe('#go')
    expect(root.style.cssText).toBe('untouched')
    expect(root.innerHTML).toBe('untouched')
  })

  it('normalizes URL values against fixed allowlists', () => {
    expect(appearanceFromSearch('?obai_theme=dark&obai_accent=orange&obai_density=compact&obai_motion=reduce')).toEqual({
      theme: 'dark', accent: 'orange', density: 'compact', motion: 'reduce',
    })
    expect(appearanceFromSearch('?obai_theme=javascript&obai_accent=%3Csvg%3E&obai_density=huge&obai_motion=auto', 'light')).toEqual({
      theme: 'light', accent: 'teal', density: 'comfortable', motion: 'system',
    })
  })

  it('requires the exact production origin, parent source, exact keys, and valid values', () => {
    const { win, doc, parent, root, listeners, sent } = embedded()
    const stop = connectAppearanceMessages(win, doc)
    expect(sent).toEqual([[{ type: EMBED_READY_EVENT }, 'https://webstudio.omnibioai.org']])
    const listener = listeners.get('message')!
    const message = { type: EMBED_THEME_EVENT, theme: 'light', accent: 'blue', density: 'compact', motion: 'reduce' }
    const deliver = (origin: string, source: unknown, data: unknown) => listener({ origin, source, data } as MessageEvent)

    deliver('https://evil.example', parent, message)
    deliver('https://webstudio.omnibioai.org', {}, message)
    deliver('https://webstudio.omnibioai.org', parent, { ...message, token: 'secret' })
    deliver('https://webstudio.omnibioai.org', parent, { ...message, username: 'reader' })
    deliver('https://webstudio.omnibioai.org', parent, { ...message, accent: 'javascript:alert(1)' })
    expect(root.dataset).toEqual({})
    expect(parseThemeMessage({ ...message, username: 'reader' })).toBeNull()

    deliver('https://webstudio.omnibioai.org', parent, message)
    expect(root.dataset).toEqual({ theme: 'light', accent: 'blue', density: 'compact', motion: 'reduce' })
    expect(root.style.cssText).toBe('untouched')
    expect(root.innerHTML).toBe('untouched')
    stop()
    expect(listeners.has('message')).toBe(false)
  })

  it('allows a development parent only when an exact origin is explicitly configured', () => {
    const valid = embedded('http://localhost:5174/')
    connectAppearanceMessages(valid.win, valid.doc, 'http://localhost:5174')
    expect(valid.sent).toEqual([[{ type: EMBED_READY_EVENT }, 'http://localhost:5174']])

    const defaultEmpty = embedded('http://localhost:5174/')
    connectAppearanceMessages(defaultEmpty.win, defaultEmpty.doc)
    expect(defaultEmpty.sent).toEqual([])
    expect(defaultEmpty.listeners.has('message')).toBe(false)

    const confused = embedded('http://localhost:5174/')
    connectAppearanceMessages(confused.win, confused.doc, 'http://localhost:5174.attacker.example')
    expect(confused.sent).toEqual([])

    const top = embedded('')
    Object.assign(top.win, { parent: top.win })
    connectAppearanceMessages(top.win, top.doc, 'http://localhost:5174')
    expect(top.sent).toEqual([])
  })
})
