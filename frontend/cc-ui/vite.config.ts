import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Admin Console dual build architecture: VITE_APP_MODE picks this
// build's output directory here (Node-side, via process.env -- Vite
// config files aren't client code) and, separately, which App component
// src/main.tsx renders client-side (via import.meta.env, which Vite
// exposes VITE_-prefixed vars into automatically). Both read the exact
// same shell env var package.json's build:admin/build:control scripts
// set -- this isn't two configuration mechanisms to keep in sync, one
// value flows into both. Unset (e.g. plain `npm run dev`/`npm run
// build`) falls back to the original single `dist` output, unchanged.
const appMode = process.env.VITE_APP_MODE
const outDir = appMode === 'admin' ? 'dist-admin' : appMode === 'control' ? 'dist-control' : 'dist'

// Server-side only: deliberately not VITE_-prefixed, because Vite injects
// every VITE_* var into browser modules and this can name an internal
// container (e.g. the DGX acceptance stack's http://cc-backend:7070).
// Unset keeps the original local-development target.
const controlCenterProxyTarget = process.env.CONTROL_CENTER_PROXY_TARGET || 'http://localhost:7070'
if (!/^https?:\/\/[^/\s]+\/?$/.test(controlCenterProxyTarget)) {
  throw new Error('CONTROL_CENTER_PROXY_TARGET must be an http(s) origin, e.g. http://localhost:7070')
}

// Vite's default host check (localhost/IPs only) stays in force; the one
// public name added here is the Cloudflare-tunnelled DGX staging Admin
// Console. Never `allowedHosts: true`.
const allowedHosts = ['admin-staging.omnibioai.org']

// Keep the local API route table identical in Vite dev and `vite preview`.
// Without the preview-side proxy, API paths such as /auth/login can fall
// through to the SPA's HTML fallback instead of reaching Control Center.
const localApiProxy = {
  '/summary': { target: controlCenterProxyTarget, changeOrigin: true },
  '/health': { target: controlCenterProxyTarget, changeOrigin: true },
  '/services': { target: controlCenterProxyTarget, changeOrigin: true },
  '/report': { target: controlCenterProxyTarget, changeOrigin: true },
  '/config': { target: controlCenterProxyTarget, changeOrigin: true },
  '/docker': { target: controlCenterProxyTarget, changeOrigin: true },
  // Control Center relays these identity/platform routes to their owning services.
  '/orgs': { target: controlCenterProxyTarget, changeOrigin: true },
  '/platform': { target: controlCenterProxyTarget, changeOrigin: true },
  '/audit': { target: controlCenterProxyTarget, changeOrigin: true },
  '/organizations': { target: controlCenterProxyTarget, changeOrigin: true },
  '/auth': { target: controlCenterProxyTarget, changeOrigin: true },
  '/dashboard': { target: controlCenterProxyTarget, changeOrigin: true },
  '/billing': { target: controlCenterProxyTarget, changeOrigin: true },
  '/sessions': { target: controlCenterProxyTarget, changeOrigin: true },
  '/tes': { target: controlCenterProxyTarget, changeOrigin: true },
  '/model-registry': { target: controlCenterProxyTarget, changeOrigin: true },
  '/workflow-bundles': { target: controlCenterProxyTarget, changeOrigin: true },
  '/rag': { target: controlCenterProxyTarget, changeOrigin: true },
  '/integration-health/data': { target: controlCenterProxyTarget, changeOrigin: true },
  '/agent-orchestrator': { target: controlCenterProxyTarget, changeOrigin: true },
  '/hipaa-compliance': { target: controlCenterProxyTarget, changeOrigin: true },
  '/security-posture/data': {
    target: controlCenterProxyTarget, changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/security-posture\/data$/, '/security-posture'),
  },
}

export default defineConfig({
  plugins: [react()],
  build: {
    outDir,
  },
  server: {
    allowedHosts,
    proxy: localApiProxy,
  },
  preview: {
    allowedHosts,
    proxy: localApiProxy,
  },
})
