/** Preserve old bookmarks without adding an extra browser-history entry. */
export function redirectLegacyTenants() {
  const match = window.location.pathname.match(/^\/tenants(?:\/(\d+))?\/?$/)
  if (!match) return
  const query = new URLSearchParams(window.location.search)
  if (match[1]) query.set('tab', 'plan-storage')
  const suffix = query.toString()
  window.history.replaceState(null, '', `/users${match[1] ? `/${match[1]}` : ''}${suffix ? `?${suffix}` : ''}`)
}
