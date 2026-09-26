import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PageErrorBoundary from './PageErrorBoundary'

let shouldThrow = true
function Flaky() {
  if (shouldThrow) throw new Error('bad response shape')
  return <div>Page content</div>
}

describe('PageErrorBoundary', () => {
  afterEach(() => { shouldThrow = true; vi.restoreAllMocks() })

  it('shows an error with Retry instead of unmounting everything', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<div><nav>Sidebar</nav><PageErrorBoundary><Flaky /></PageErrorBoundary></div>)
    expect(screen.getByText('Sidebar')).toBeInTheDocument()
    expect(screen.getByText(/This page couldn't be displayed/)).toBeInTheDocument()

    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(screen.getByText('Page content')).toBeInTheDocument()
  })

  it('renders children untouched when nothing fails', () => {
    shouldThrow = false
    render(<PageErrorBoundary><Flaky /></PageErrorBoundary>)
    expect(screen.getByText('Page content')).toBeInTheDocument()
  })
})
