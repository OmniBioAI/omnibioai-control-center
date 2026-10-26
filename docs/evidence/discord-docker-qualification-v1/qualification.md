# Discord Docker qualification — V1 harness / V2 safety closure

Status: **PARTIAL — safety review PASS, Docker E2E blocked by access inconsistency and disposable Redis startup failure**.

V2 resolved the independent review findings in the existing harness: immutable-ID ownership checks, one-off runner tracking, idempotent exceptional cleanup, separately guaranteed after-inventory, isolated subnet selection/revalidation, collision rejection, and fake-Docker exceptional-path tests. Fresh independent review returned PASS across all ten requested areas. The Docker harness was attempted only after that PASS.

The most recent attempt created a unique internal network and volume plus labeled containers; `state-init` exited successfully, but the disposable Redis container exited with code 1, preventing dependent mock/router readiness and E2E launch. The harness removed only manifest-owned resources. Its before/after comparison passed: 178 protected container fingerprints on both sides; no changed/missing protected containers, no lost protected network/volume rows, and no remaining harness resources. A subsequent Docker API access reconfirmation from the ordinary context returned `permission denied` for `/var/run/docker.sock`; therefore Docker-dependent work stopped at that boundary. The readiness failure needs permitted, non-secret diagnostics before changing Redis configuration.

Current evidence: Docker E2E 0/6; community exclusions 0/3; crash recovery 0/18 executed (14 historical scenarios applicable as currently worded; 4 queue/worker/config-contract cases inapplicable or conditional); rollback NOT_VERIFIED; V2 Docker-free harness tests 16/16 PASS; existing focused suite 134/134 from prior evidence; full restricted backend 2,221 passed, 13 environment failures, 97.95% (historical, not rerun in V2); verified destinations 0/6; production runtimes 0/7; live canaries 0/6; release gates remain 3/12 (25.0%); production NO-GO.

No production resources were intentionally targeted; no live Discord messages or production credentials were used. See `isolation-review.md`, `v2-execution-history.md`, `architecture.md`, `release-gates.md`, and `operator-handoff.md`.
