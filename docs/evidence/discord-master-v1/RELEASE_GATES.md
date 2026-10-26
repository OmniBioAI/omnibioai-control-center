# Authoritative release-gate matrix — Master V1

Source baseline: HEAD `f37ce8c952f917f607e9923cbb47dda8b0406a7a` plus the
dirty Discord/backend overlay documented in `BASELINE.md` and
`source-snapshot.md`. User-specified gate criteria govern; no contrary
executable acceptance definition was found.

The earlier 3/12 matrix is stale: it predates the socket-capable 2,239-test,
98.01% result. V10-D reconciled this by adding G8. V7/V8's 5/12 count is not
comparable because it counted software-path migration toward G5 without
deployed destination equivalence. Current evidence supports 4/12, not 3/12:
G1, G2, G6, G8.

| Gate | Acceptance criteria | Status | Current evidence / review | Owner and next action |
|---|---|---|---|---|
| G1 Central router | Synchronous central routing and supported delivery behavior pass | PASS — code/test scope | 152 focused tests and 2,242 full backend tests pass; no live behavior implied. Fresh independent fail-closed review PASS | Backend; keep legacy fallback disabled absent destination review |
| G2 Event mappings | All 11 mapped events route only to the six intended contracts | PASS — static/test scope | V10-D routing evidence plus current focused regression; no real channel identity proof | Router integration; retain live binding blocker under G3 |
| G3 Six real destinations | Six distinct verified guild/channel identities and deployed bindings | BLOCKED | V12 readback 0/6; no authorized metadata access | Discord/deployment operator supplies sanitized IDs/bindings |
| G4 Seven source runtimes | Seven authenticated production source identities and IAM results | BLOCKED | V12 readback 0/7; no runtime readback | Source/IAM owners supply identity and sanitized auth evidence |
| G5 Legacy migration | All publishers migrated/retired with destination equivalence | NOT_VERIFIED | Track E says 4/5; Control Center fallback destination and docs direct path remain; master code now defaults fail-closed but deployed equivalence unknown | Integration + deployment; verify every deployed publisher/destination |
| G6 IAM security | Source authentication, allowlists, authorization and rejection controls pass | PASS — synthetic/test scope | Current focused IAM suite passed; production IAM runtime is BLOCKED per V12. Independent review PASS is limited to fail-closed notification behavior | IAM/backend; readback required for any live claim |
| G7 Crash recovery | Applicable scenarios pass Docker-free and approved Docker-backed recovery | BLOCKED | Historical 18/18 reviewed, 14/14 Docker-free reported; current 7/7 crash module passes with DCR-01/05 strengthened; 0/14 Docker-backed | D/A; cover DCR-04 in-flight boundary, review fault runner, then authorized operator run |
| G8 Full backend regression | Full suite passes with >=98% coverage | PASS — current overlay | 2,242 passed, 74 subtests, 98.01% in approved loopback-capable run | Backend quality; rerun affected suite after integration edits |
| G9 ARM64 provenance | Exact clean source → immutable native ARM64 image, verified SBOM/provenance and deployment config | FAIL | Track F: no current-source image digest/SBOM/provenance; Dockerfile inputs unpinned; current source dirty | Release engineering; create scoped clean candidate, pin inputs, build/attest/verify natively |
| G10 Live canaries | Six authorized canaries to six verified destinations | BLOCKED | 0/6; no destination identities or explicit canary approval; none sent | User/deployer + Discord admin; explicit approval required |
| G11 Rollback/recovery | Verified compatible rollback or separately accepted first-release recovery rehearsal | NOT_VERIFIED | No compatible historical multichannel image; first-release recovery plan exists but not rehearsed | Release engineering; qualify immutable candidate and rehearse disposable recovery |
| G12 Production deployment | Explicit deployment approval | BLOCKED | No approval; deployment is not authorized and none attempted | User/release authority provides separate explicit approval |

Counts: **4 PASS, 5 BLOCKED, 2 NOT_VERIFIED, 1 FAIL**. The readiness
percentage is the pass fraction `4/12 = 33.3%`, not a claim that the
production system is 33.3% deployed or safe. `PRODUCTION_READY=NO`.
