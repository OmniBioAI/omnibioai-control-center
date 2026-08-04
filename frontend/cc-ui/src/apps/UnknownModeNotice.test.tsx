import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import UnknownModeNotice from './UnknownModeNotice'

describe('UnknownModeNotice', () => {
  it('shows a configuration error mentioning the required values', () => {
    render(<UnknownModeNotice mode={undefined} />)
    expect(screen.getByText('Configuration error')).toBeInTheDocument()
    expect(screen.getByText(/VITE_APP_MODE must be set to "admin" or "control"/)).toBeInTheDocument()
  })

  it('echoes back an unrecognized mode value for debugging', () => {
    render(<UnknownModeNotice mode="bogus" />)
    expect(screen.getByText(/"bogus"/)).toBeInTheDocument()
  })

  it('shows undefined explicitly rather than a blank value', () => {
    render(<UnknownModeNotice mode={undefined} />)
    expect(screen.getByText(/got: undefined/)).toBeInTheDocument()
  })
})
