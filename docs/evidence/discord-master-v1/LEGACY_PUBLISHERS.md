# Legacy publisher integration — Master V1

## Development change

An audit found `notify()` sent caller-supplied legacy webhook URLs whenever the
central router URL and infrastructure key were not both present. The same path
also allowed a partially configured central router to fall through to direct
delivery. Because destination identities and runtime migration are not
verified, this was an unsafe fail-open compatibility behavior.

The development source now fails closed by default:

- Direct legacy delivery requires the explicit
  `DISCORD_LEGACY_WEBHOOK_FALLBACK=enabled` opt-in.
- The opt-in path validates the target as an HTTPS Discord webhook URL before
  making any request; arbitrary hosts/addresses are rejected.
- If either central router setting is present, both must be present; an
  incomplete pair returns failure and never attempts direct webhook delivery.
- A failed central submission still never falls back, preventing a second
  delivery path after an ambiguous or rejected central attempt.
- Direct fallback tests opt in explicitly; new tests assert default denial and
  rejection of each partial central configuration.

Focused unit suite: 20 passed, 2 subtests passed. Integrated Discord/router/IAM
suite after the change: 152 passed, 2 subtests passed. Full backend regression
also passed; details are in `BACKEND_REGRESSION.md`.

This is source-only development behavior. No deployed environment variable,
webhook, route, secret, or publisher was changed. The compatibility opt-in
must not be enabled in production until its destination is identified and a
separately approved migration/alert-visibility plan exists.

## Remaining publisher audit

The V12 / Track E audit still identifies a direct legacy path in
`omnibioai-docs/scripts/deploy-docs.sh`. RAG and Workbench source use the
central publisher, but their deployed runtimes were not inspected. Track E
reported 4/5 paths migrated/retired; Control Center fallback equivalence and
legacy destination identity remain unknown. Production result remains
`LEGACY_PUBLISHERS=PARTIAL`, not PASS.
