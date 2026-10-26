# Release gates

| Gate | Result | Evidence / blocker |
|---|---|---|
| G1 Central router | PASS (implementation/tests) | Real API process wired in harness; V2 container startup blocked at disposable Redis readiness, before router readiness/E2E |
| G2 Event mappings | PASS | 11/11 mocked mapping tests |
| G3 Verified Discord destinations | BLOCKED | 0/6 verified identities/webhooks |
| G4 Authenticated production source runtimes | BLOCKED | 0/7 production credentials/runtime qualifications |
| G5 Legacy publisher migration | NOT_VERIFIED | Production publisher migration/equivalence remains unverified |
| G6 IAM security | PASS | Focused IAM suite in prior evidence; synthetic Docker IAM path not executed |
| G7 Full crash recovery | NOT_VERIFIED | 0/18 Docker scenarios |
| G8 Full backend regression and coverage | NOT_VERIFIED | 2,221 pass/13 environment failures; 97.95%, below 98.00% target |
| G9 ARM64 provenance/deployment | NOT_VERIFIED | V2 built and inspected a local Linux ARM64 image with source labels/layer linkage; registry provenance and reproducible-build evidence remain absent; no deployment |
| G10 Authorized live canaries | BLOCKED | 0/6; no approval and no messages sent |
| G11 Rollback | NOT_VERIFIED | No legitimate compatible prior Discord candidate |
| G12 Explicit production deployment approval | BLOCKED | Not requested or granted; deployment prohibited |

Pass count: **3/12 (25.0%)**. G1/G2/G6 pass based on implementation and existing focused evidence; production: **NO-GO**. V2 Docker isolation comparison passed for the attempted run, but this does not change destination/source, crash-recovery, live-canary, or rollback gates.
