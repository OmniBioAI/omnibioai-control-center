import fs from 'node:fs'
import path from 'node:path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = path.resolve(process.cwd(), 'src')
const TOKEN_BLOCK = /\/\* color-token-mapping:start[\s\S]*?\/\* color-token-mapping:end \*\//g
const LITERAL_COLOR = /#[\da-f]{3,8}\b|\brgba?\s*\(/gi
const EXPLICIT_EXCEPTIONS: ReadonlyArray<{ file: string; value: string; reason: string }> = []

function productionStyleSources(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return productionStyleSources(fullPath)
    if (!/\.(css|ts|tsx)$/.test(entry.name) || entry.name.includes('.test.') || entry.name === 'test-setup.ts') return []
    return [fullPath]
  })
}

it('uses semantic color tokens outside the single marked mapping block', () => {
  const indexCss = fs.readFileSync(path.join(SOURCE_ROOT, 'index.css'), 'utf8')
  expect(indexCss.match(TOKEN_BLOCK)).toHaveLength(1)

  const failures = productionStyleSources(SOURCE_ROOT).flatMap((file) => {
    const relative = path.relative(SOURCE_ROOT, file)
    const source = fs.readFileSync(file, 'utf8').replace(TOKEN_BLOCK, '')
    return Array.from(source.matchAll(LITERAL_COLOR)).flatMap((match) => {
      const value = match[0]
      return EXPLICIT_EXCEPTIONS.some((exception) => exception.file === relative && exception.value === value)
        ? []
        : [`${relative}: ${value}`]
    })
  })

  expect(EXPLICIT_EXCEPTIONS).toEqual([])
  expect(failures).toEqual([])
})

it('vendors @omnibioai/design-tokens 1.1.0 without c8, scripts, or a nested lockfile', () => {
  const vendor = path.resolve(process.cwd(), 'vendor/omnibioai-design-tokens')
  const metadata = JSON.parse(fs.readFileSync(path.join(vendor, 'package.json'), 'utf8'))
  expect(metadata.name).toBe('@omnibioai/design-tokens')
  expect(metadata.version).toBe('1.1.0')
  expect(metadata.scripts).toBeUndefined()
  expect(metadata.devDependencies).toBeUndefined()
  expect(JSON.stringify(metadata)).not.toContain('c8')
  expect(fs.existsSync(path.join(vendor, 'package-lock.json'))).toBe(false)
})
