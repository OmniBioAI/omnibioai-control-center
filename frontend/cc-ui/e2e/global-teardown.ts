import fs from 'node:fs/promises'

export default async function globalTeardown() {
  // Authentication state is only a run-local optimization. Remove it even
  // when the suite has failures; the directory itself is gitignored.
  await fs.rm('e2e/.auth', { recursive: true, force: true })
}
