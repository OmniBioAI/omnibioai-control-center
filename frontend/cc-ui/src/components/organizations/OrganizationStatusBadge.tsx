// Phase 3 PR3A: this component's implementation moved to the shared
// ../StatusBadge.tsx (the "active"/"suspended" vocabulary is identical
// for organizations and users -- see that file's own comment). Kept as
// a thin re-export, not deleted, so OrganizationTable.tsx/
// OrganizationDetailPage.tsx (Phase 3 PR2) need zero changes.
export { default } from '../StatusBadge'
