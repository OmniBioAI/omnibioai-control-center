# Release gate reconciliation

Current workstream evidence only; historical results are not upgraded by
inference.

| Gate | Result | Basis |
|---|---|---|
| G1 Central router | PASS | Fresh focused Discord tests pass |
| G2 Event mappings | PASS | 11 mapping contracts; mock routes 6/6 |
| G3 Six channel identities | BLOCKED | 0/6 independently verified |
| G4 Seven configured source runtimes | BLOCKED | 0/7 credentials/runtime qualification |
| G5 Legacy publisher compatibility | NOT_VERIFIED | Conservative 4/5 disposition; runtime equivalence absent |
| G6 IAM security | PASS | 15 isolated IAM API tests included in focused run |
| G7 Full crash recovery | NOT_VERIFIED | 0/18 Docker scenarios; maintained harness absent |
| G8 Full regression and coverage | BLOCKED | Current run 97.95%, 13 sandbox loopback failures; cross-repo incomplete |
| G9 ARM64 images and provenance | NOT_VERIFIED | ARM64/digest inventory passes; exact source/build provenance absent |
| G10 Six live canaries | BLOCKED | 0/6; no publication authorization |
| G11 Disposable rollback | NOT_VERIFIED | Reviewed stack and candidate/prior image pair absent |
| G12 Production approval | BLOCKED | Not granted; deployment prohibited |

**PASS=3/12 (25.0%).** Five gates are BLOCKED and four are NOT_VERIFIED.
Technical qualification is incomplete; production is **NO-GO** and unchanged.
