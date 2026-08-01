// Same mark used in Header.tsx -- kept as a separate component here so the
// login page and the authenticated shell can't drift from each other.
interface Props {
  size?: number
}

export default function AdminLogo({ size = 34 }: Props) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width={size} height={size} style={{ flexShrink: 0 }}>
      <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="var(--accent)" strokeWidth="1.8" />
      <path
        d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20"
        stroke="var(--accent)"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="16" cy="15" r="2.2" fill="var(--accent)" />
    </svg>
  )
}
