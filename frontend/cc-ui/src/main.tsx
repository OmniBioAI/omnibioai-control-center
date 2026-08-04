import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AdminApp from './apps/AdminApp.tsx'
import ControlApp from './apps/ControlApp.tsx'
import UnknownModeNotice from './apps/UnknownModeNotice.tsx'

// Admin Console dual build architecture: VITE_APP_MODE is set at build
// time (package.json's build:admin/build:control scripts) -- 'admin'
// selects AdminApp (enterprise console + ops pages, admin.omnibioai.org),
// 'control' selects ControlApp (ops pages only, control.omnibioai.org).
//
// Written as a static, directly-compared `import.meta.env.VITE_APP_MODE`
// conditional (not an intermediate function parameter, not a dynamic
// import()) deliberately: Vite inlines import.meta.env.* as literal
// string constants at build time, which lets Rollup's minifier
// constant-fold the losing branch away and then tree-shake its now-
// unreachable AdminApp/ControlApp import entirely out of that build's
// output. This is what actually keeps Organizations/Users/Roles/Teams
// code out of the control build (a real bundle-content fact, not just a
// hidden UI element) -- see docs/admin-console-build.md for how this is
// verified against the real build output.
//
// Fails safely for an unset or unrecognized mode (e.g. `vite dev` run
// without VITE_APP_MODE, or a typo) -- shows an explicit configuration
// error (UnknownModeNotice, unit tested on its own) rather than silently
// defaulting to either app.
const mode = import.meta.env.VITE_APP_MODE

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {mode === 'admin' ? <AdminApp /> : mode === 'control' ? <ControlApp /> : <UnknownModeNotice mode={mode} />}
  </StrictMode>,
)
