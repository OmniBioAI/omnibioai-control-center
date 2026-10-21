# Storage Dashboard metadata-only integration boundary

The previous eight-directory-bind overlay was unsafe because read-only binds
still allowed Control Center to read storage contents. It has been replaced
with one read-only bind of the signed, metadata-only host snapshot. No shared
Compose file or release pin is changed by this candidate work.

Read-only rendering of the effective production Compose inputs plus the new
overlay confirmed the candidate image and exactly one new, read-only snapshot
bind. It also exposed three pre-existing writable binds to SIF work,
reference, and test-data directories. Those were not added by this candidate,
but they mean the effective production Control Center still has storage data
access and does not meet the new security requirement. Removing or narrowing
them requires acknowledgment from the shared Compose owner; no such edit has
been made.

The host collector and signed snapshot contract are documented in
`STORAGE_DASHBOARD_TELEMETRY_P0_V1.md`. Before any deployment, the system
owner must provision the root-only Ed25519 signing key on the host, pin its
public key into Control Center configuration, and arrange the host collector
timer. This work did not touch host `/etc`, `/run`, disks, backup repositories,
or production services.

The shared Compose owner and release-pin owner have not acknowledged this
change. The running Dev Hub was previously observed as active; no unavailable
communication endpoint was treated as evidence of inactivity. No shared
Compose file or release pin was edited. The production rollback image
`obai-control-center:2572cd551bdb` remains the saved rollback target.

Production deployment remains prohibited. A separate explicit authorization
is required after owner coordination and host key/snapshot provisioning. The
candidate must then be deployed only to Control Center, with the single
snapshot bind and pinned public key. Verify API 401/403 behavior, metrics,
freshness failure behavior, and continued Restic unavailability before any
Storage 1.0 readiness decision. The candidate collector was also run in the
workspace namespace, where none of the configured host mount identities
matched; it correctly returned UNAVAILABLE. A successful host collection
using the DGX mount namespace and provisioned signing key remains required.
