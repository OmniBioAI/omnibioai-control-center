# Exact blockers — Master V1

1. **Docker execution access:** normal `docker info` is denied on the socket.
   No daemon identity, protected inventory, Redis/mock health, cleanup, six
   E2E, community exclusions, or Docker recovery results can be claimed.
2. **Docker safety qualification:** the integrated router source has a fresh
   independent code review PASS at digest
   `b7bf95c9f9bd1af4da8a2d90a7e325261a304f001781a453334e9fa8c27ec725`, but
   this does not authorize runtime execution. The daemon preflight is denied
   and harness runtime qualification remains outstanding.
3. **Production readbacks:** authorized sanitized Discord guild/channel and
   router binding metadata are missing for 6 destinations; deployed workload
   identity/auth/IAM metadata is missing for 7 sources.
4. **Legacy migration:** destination equivalence for remaining legacy direct
   publishers is unknown. The Control Center development code now fails closed
   unless direct fallback is explicitly enabled; the docs publisher retains a
   direct fallback. No deployed environment was changed.
5. **Crash recovery depth:** Docker-free evidence is historical 14/14, but
   DCR-01/04/05 model boundaries have limitations and no Docker fault tests
   ran. The scenario plan is not execution evidence.
6. **ARM64 provenance:** no clean current-source release image, immutable
   digest, verified SBOM or source-bound attestation; build inputs need
   pinning.
7. **Rollback:** no compatible prior multichannel image. First-release
   recovery is planned but not rehearsed.
8. **Canaries and deployment:** 0/6 live canaries and explicit production
   deployment approval is absent. Neither can be supplied by an agent.

No blockers were bypassed. All local test and source-evidence work that did
not require unavailable access was completed.
