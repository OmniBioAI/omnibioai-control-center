'use strict';
// Runs before every `npm run build` (npm "prebuild" hook, so also in the Docker
// build stage). Fails the build if any VITE_* variable outside the explicit PUBLIC
// allowlist is present -- in the environment or in a .env* file.
//
// Vite inlines VITE_* variables into the PUBLIC JavaScript bundle. A developer's
// git-ignored local .env.production is copied into the Docker build by
// `COPY frontend/cc-ui/ ./`. Sibling frontends (RAG UI, LIMS) once published
// credentials this way. Only public configuration (URLs, flags, client ids) may be
// a VITE_ variable.
//
// Prints variable NAMES only, never values.
const fs = require('fs');
const path = require('path');

const rootArg = process.argv.indexOf('--root');
const root = path.resolve(rootArg > -1 ? process.argv[rootArg + 1] : path.join(__dirname, '..'));
const PUBLIC = new Set(JSON.parse(fs.readFileSync(path.join(__dirname, 'public-browser-config.json'), 'utf8')));

const present = new Set(Object.keys(process.env).filter((k) => k.startsWith('VITE_')));
for (const file of fs.readdirSync(root).filter((f) => /^\.env(\..+)?$/.test(f))) {
  for (const line of fs.readFileSync(path.join(root, file), 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?(VITE_[A-Za-z0-9_]+)\s*=/);
    if (match) present.add(match[1]);
  }
}

const forbidden = [...present].filter((name) => !PUBLIC.has(name)).sort();
if (forbidden.length > 0) {
  console.error('\nRefusing to build: these VITE_* variables are not approved public configuration:\n');
  for (const name of forbidden) console.error(`  - ${name}`);
  console.error(
    '\nVite compiles VITE_* variables into the PUBLIC JavaScript bundle. Never pass a token, password, API key\n' +
      'or other reusable credential this way, including through a local .env.production that the Docker build\n' +
      'copies in. Remove the variable. If it really is public configuration, add it to\n' +
      'scripts/public-browser-config.json in a reviewed change.\n',
  );
  process.exit(1);
}
