import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
}

const VARIANT_STYLE: Record<Variant, React.CSSProperties> = {
  primary: { background: 'var(--accent)', color: '#000', border: 'none' },
  secondary: { background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)' },
  ghost: { background: 'transparent', color: 'var(--muted)', border: '1px solid transparent' },
}

/** Admin Console Phase 2 design system: the one button style every page
 * currently hand-rolls inline (Header.tsx's Refresh/Generate Report
 * buttons predate this and are untouched). New code should use this. */
export default function Button({ variant = 'secondary', style, disabled, ...rest }: Props) {
  return (
    <button
      disabled={disabled}
      style={{
        fontSize: 13, fontWeight: 600, padding: '7px 15px',
        borderRadius: 'var(--radius-sm)',
        display: 'inline-flex', alignItems: 'center', gap: 6,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...VARIANT_STYLE[variant],
        ...style,
      }}
      {...rest}
    />
  )
}
