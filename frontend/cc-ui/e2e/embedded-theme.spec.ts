import { expect, test, type FrameLocator } from '@playwright/test'

async function auditTextContrast(frame: FrameLocator) {
  return frame.locator('body').evaluate((body) => {
    const parse = (value: string) => (value.match(/[\d.]+/g) || []).map(Number)
    const composite = (front: number[], back: number[]) => front.length > 3 && front[3] < 1
      ? front.slice(0, 3).map((channel, index) => channel * front[3] + back[index] * (1 - front[3]))
      : front.slice(0, 3)
    const luminance = ([r, g, b]: number[]) => {
      const channels = [r, g, b].map((value) => {
        const s = value / 255
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    }
    const contrast = (a: number[], b: number[]) => {
      const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
      return (light + 0.05) / (dark + 0.05)
    }

    return [...body.querySelectorAll<HTMLElement>('*')].flatMap((element) => {
      const style = getComputedStyle(element)
      const hasText = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim())
      if (!hasText || element.closest('[aria-hidden="true"]') || style.display === 'none' || style.visibility === 'hidden') return []
      const box = element.getBoundingClientRect()
      if (!box.width || !box.height) return []

      const layers: HTMLElement[] = []
      for (let layer: HTMLElement | null = element; layer && layer !== document.documentElement; layer = layer.parentElement) layers.push(layer)
      let backdrop = parse(getComputedStyle(document.body).backgroundColor).slice(0, 3)
      for (const layer of layers.reverse()) {
        const color = parse(getComputedStyle(layer).backgroundColor)
        if (color.length >= 3 && !(color[0] === 0 && color[1] === 0 && color[2] === 0 && color[3] === 0)) backdrop = composite(color, backdrop)
      }
      const ratio = contrast(parse(style.color), backdrop)
      return ratio < 4.5 ? [{ text: element.textContent?.trim().slice(0, 60), ratio }] : []
    })
  })
}

const cases = [
  { theme: 'light', accent: 'purple', rgb: 'rgb(112, 48, 160)' },
  { theme: 'dark', accent: 'teal', rgb: 'rgb(0, 229, 160)' },
] as const

for (const width of [1440, 390]) {
  for (const appearance of cases) {
    test(`embedded ${appearance.theme}+${appearance.accent} at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
      await page.route('**/*', async (route) => {
        if (route.request().resourceType() === 'fetch') {
          await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"test fixture unavailable"}' })
        } else {
          await route.continue()
        }
      })
      await page.goto('/')
      await page.setContent(`<style>html,body{margin:0;width:100%;height:100%;overflow:hidden}iframe{border:0;width:100%;height:100%}</style><iframe title="Embedded Control Center" src="/?obai_theme=${appearance.theme}&obai_accent=${appearance.accent}&obai_density=comfortable&obai_motion=system"></iframe>`)

      const embedded = page.frameLocator('iframe')
      await expect(embedded.getByRole('heading', { name: 'Platform Overview' })).toBeVisible()
      await expect(embedded.locator('html')).toHaveAttribute('data-embedded', 'true')
      await expect(embedded.locator('html')).toHaveAttribute('data-theme', appearance.theme)
      await expect(embedded.locator('html')).toHaveAttribute('data-accent', appearance.accent)
      await expect(embedded.locator('.control-brand-bar')).toHaveCSS('display', 'none')
      await expect(embedded.locator('.cc-tabbar')).toBeVisible()
      await expect(embedded.locator('.control-content')).toHaveCSS('padding-top', '44px')

      const activeTab = embedded.getByRole('tab', { name: 'Overview' })
      await expect(activeTab).toHaveCSS('color', appearance.rgb)
      await expect(activeTab).toHaveCSS('border-bottom-color', appearance.rgb)
      expect(await auditTextContrast(embedded)).toEqual([])

      const screenshot = `/tmp/n11a-control-${appearance.theme}-${appearance.accent}-${width}.png`
      await page.screenshot({ path: screenshot, fullPage: true })
      await testInfo.attach(`embedded-${appearance.theme}-${appearance.accent}-${width}`, {
        path: screenshot,
        contentType: 'image/png',
      })
    })
  }
}
