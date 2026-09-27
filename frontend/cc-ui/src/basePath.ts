// Vite's base config drives assets, API defaults and browser navigation.
// Standalone builds keep '/', while Studio uses --base=/_svc/control/.
export function appBase(): string {
  return (import.meta.env.BASE_URL ?? '/').replace(/\/+$/, '')
}

export function appPath(path: string): string {
  return `${appBase()}${path}`
}

export function localPath(pathname: string): string {
  const base = appBase()
  return base && (pathname === base || pathname.startsWith(`${base}/`))
    ? pathname.slice(base.length) || '/'
    : pathname
}

export function apiBase(): string {
  return ((import.meta.env.VITE_API_BASE as string | undefined) ?? appBase()).replace(/\/+$/, '')
}
