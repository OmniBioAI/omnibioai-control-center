# Independent isolation review — V2 closure

Status: **PASS — independent source review; Docker execution permitted conditionally**.

The independent reviewer re-reviewed the corrected harness and confirmed PASS for ownership validation, one-off runner lifecycle, partial startup and exceptional cleanup, after-inventory preservation, internal network isolation, unique-volume isolation, secret isolation, bounded resources, and destructive command targeting. Exact cleanup uses immutable IDs, exact run/workstream labels, and ownership-manifest membership; resource names alone are not authorization. The reviewer also specifically confirmed the state-init command sets mode while UID 0 owns the disposable volume root, then transfers ownership using only `CAP_CHOWN`.

The source-level safety review passed before this execution attempt. Docker access was then denied by the ordinary execution context (`permission denied ... /var/run/docker.sock`) during access reconfirmation. The already authorized execution mechanism had earlier run the harness, but access is not currently consistent. By policy, no further Docker-dependent commands were run after that denial. The harness attempt itself started only manifest-labeled disposable resources and performed owned-resource cleanup; its after-inventory comparison passed (178 protected container fingerprints before/after, no lost protected network/volume rows, no remaining run resources). This is evidence of that attempt only, not permission to use another execution boundary.

Independent review findings:

| Finding | Result | Evidence / scope |
|---|---|---|
| Ownership validation | PASS | Exact labels, IDs, manifest membership, full network IPAM, expected volume/image identity; two-phase validation |
| One-off runner lifecycle | PASS | Runner has ownership labels and no `--rm`; cleanup discovers its immutable ID |
| Partial startup | PASS | Labeled partially-created resources are enumerated and individually validated before removal |
| Exceptional cleanup | PASS | `finally`, signal handler, timeout/error paths, idempotent missing-resource handling; cleanup failures retain manifest |
| After-inventory preservation | PASS | Cleanup and after-inventory errors captured independently; failed inventory means isolation FAIL |
| Network isolation | PASS | Internal unique network, collision checks, host-route/Docker-IPAM-aware subnet selection and pre-start revalidation |
| Volume isolation | PASS | Unique named volume, collision checks, exact labels and manifest membership |
| Secret isolation | PASS | Synthetic-only values, no Docker socket, no production secret reads; inventory avoids environment values |
| Resource limits | PASS | Per-service CPU, memory, PID, log, tmpfs and bounded timeout limits |
| Destructive command targeting | PASS | Individual immutable IDs only; no `down`, prune, prefix-only or global cleanup |

No review result implies E2E or production readiness. See `v2-execution-history.md` for the failed readiness attempt and exact boundary.
