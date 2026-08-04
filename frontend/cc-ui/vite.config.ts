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

export default defineConfig({
  plugins: [react()],
  build: {
    outDir,
  },
  server: {
    proxy: {
      '/summary': { target: 'http://localhost:7070', changeOrigin: true },
      '/health': { target: 'http://localhost:7070', changeOrigin: true },
      '/services': { target: 'http://localhost:7070', changeOrigin: true },
      '/report': { target: 'http://localhost:7070', changeOrigin: true },
      '/config': { target: 'http://localhost:7070', changeOrigin: true },
      '/docker': { target: 'http://localhost:7070', changeOrigin: true },
      // Phase 3 PR2 -- Organizations page, proxied through control-center's
      // own backend (routes_org_proxy.py) to reach omnibioai-auth, same
      // reasoning as every entry above.
      '/orgs': { target: 'http://localhost:7070', changeOrigin: true },
      '/platform': { target: 'http://localhost:7070', changeOrigin: true },
      '/auth': { target: 'http://localhost:7070', changeOrigin: true },
    },
  },
})
