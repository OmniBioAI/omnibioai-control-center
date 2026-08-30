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
      // PR13 -- org-scoped custom role catalog CRUD (RolesPage.tsx),
      // proxied through control-center's own backend (routes_role_proxy.py)
      // to omnibioai-auth's newer /organizations/{id}/... surface. Missing
      // here meant `npm run dev` 404'd every fetchOrganizationRoles/
      // fetchOrganizationPermissions/createOrganizationRole/etc call --
      // caught while setting up a local run to screenshot PR13's UI.
      '/organizations': { target: 'http://localhost:7070', changeOrigin: true },
      '/auth': { target: 'http://localhost:7070', changeOrigin: true },
      // PR10 -- Live Platform Dashboard, proxied through control-center's
      // own backend (routes_dashboard.py), same reasoning as every entry
      // above.
      '/dashboard': { target: 'http://localhost:7070', changeOrigin: true },
      // PR14.5C -- Billing dashboard/invoice UI, proxied through
      // control-center's own backend (routes_billing_proxy.py) to reach
      // omnibioai-billing, same reasoning as every entry above.
      '/billing': { target: 'http://localhost:7070', changeOrigin: true },
      // PR-C -- Sessions page (SessionsPage.tsx), proxied through
      // control-center's own backend (routes_sessions_proxy.py) to
      // omnibioai-auth's self-service /sessions endpoints, same
      // reasoning as every entry above. Same production nginx gap class
      // PR13's/PR E's own comments here already warned about if this
      // entry were skipped.
      '/sessions': { target: 'http://localhost:7070', changeOrigin: true },
      // PR E (Admin Console Production Hardening) -- PR A1-A4 added
      // these four routers (routes_tes_proxy.py, routes_model_registry_
      // proxy.py, routes_workflow_bundles_proxy.py, routes_rag_proxy.py)
      // but never added the matching dev-proxy entry here, same gap
      // PR13's own comment above already warned about for /organizations
      // ("Missing here meant `npm run dev` 404'd..."). `npm run dev`
      // couldn't reach any of these four pages' APIs until now -- the
      // same production nginx gap this PR also fixes in
      // docker/nginx/api-proxy.conf.
      '/tes': { target: 'http://localhost:7070', changeOrigin: true },
      '/model-registry': { target: 'http://localhost:7070', changeOrigin: true },
      '/workflow-bundles': { target: 'http://localhost:7070', changeOrigin: true },
      '/rag': { target: 'http://localhost:7070', changeOrigin: true },
      '/integration-health/data': { target: 'http://localhost:7070', changeOrigin: true },
      // Agentic AI nav item (feature/agentic-ai-navbar), proxied through
      // control-center's own backend (routes_agent_orchestrator_proxy.py)
      // to omnibioai-workbench's agent_orchestrator service. Added
      // alongside its route, unlike /tes, /model-registry, /workflow-
      // bundles, /rag above -- this repo's own comment on those four
      // documents exactly the "npm run dev 404s" gap that skipping this
      // entry would repeat.
      '/agent-orchestrator': { target: 'http://localhost:7070', changeOrigin: true },
      // Admin Console HIPAA Compliance Report -- persistent change
      // history, proxied through control-center's own in-process router
      // (routes_hipaa_compliance.py, not a routes_*_proxy.py relay --
      // this repo's own hipaa_compliance/ package owns the data). Same
      // "missing here means npm run dev 404s" gap class every entry
      // above already warns about.
      '/hipaa-compliance': { target: 'http://localhost:7070', changeOrigin: true },
      // SP-3 -- keep the Security Posture SPA deep link separate from its
      // browser data path; production nginx applies the same rewrite.
      '/security-posture/data': {
        target: 'http://localhost:7070', changeOrigin: true,
        rewrite: path => path.replace(/^\/security-posture\/data$/, '/security-posture'),
      },
    },
  },
})
