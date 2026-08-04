import type { Activity } from 'lucide-react'

/**
 * lucide-react doesn't export its shared `LucideIcon`/`LucideProps`
 * type names -- every icon is individually generated with the same
 * exact type shape, so any one of them (Activity, arbitrarily) works as
 * a stand-in to derive that shared shape from. Used everywhere this
 * codebase accepts "some lucide icon component" as a prop.
 */
export type IconComponent = typeof Activity
