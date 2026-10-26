# V4 release-gate matrix

Source HEAD: `f37ce8c952f917f607e9923cbb47dda8b0406a7a`. Gate definitions preserved.

| Gate | Result | Evidence / remaining acceptance |
|---|---|---|
| G1 Central router | PASS (implementation scope) | Existing central publisher and focused historical tests; actual container router did not reach ready in latest attempt |
| G2 Event mappings | PASS (mapping/test scope) | Existing 11 mapping contracts and earlier mocked tests; Docker routes remain 0/6 |
| G3 Six verified destinations | BLOCKED | 0/6 real guild/channel/webhook identities and secret references verified |
| G4 Seven authenticated production runtimes | BLOCKED | 0/7 production credentials/runtime qualifications; source names exist in prior matrix only |
| G5 Legacy publisher migration | NOT_VERIFIED | Source-level migration exists, but every production publisher/cutover/equivalence has not been independently confirmed |
| G6 IAM | PASS (code/test scope) | Existing IAM contract and historical focused tests; current backend tests not runnable in installed Python environment |
| G7 Crash recovery | NOT_VERIFIED | 0/18 executed; 14 applicability labels are provisional and need independent acceptance |
| G8 Backend regression/coverage | BLOCKED | Historical 2,221 pass/13 environment failures/97.95%; V4 full focused run collection blocked by missing dependencies |
| G9 ARM64 source/image provenance | NOT_VERIFIED | V2 local image platform/ID/layer relation recorded; current source tree is dirty, no reproducible build or deployment digest chain |
| G10 Authorized live canaries | BLOCKED | 0/6; no explicit authorization |
| G11 Rollback | NOT_VERIFIED | No legitimate compatible prior Discord candidate found |
| G12 Explicit production approval | BLOCKED | Not granted; production deployment is prohibited in this workstream |

PASS count using unchanged gate definitions: **3/12 = 25.0%**. Overall verified release acceptance is not 100%. Production is **NO-GO**.
