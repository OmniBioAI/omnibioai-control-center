# Crash recovery — Master V1

Historical scenario IDs DCR-01 through DCR-18 and dispositions remain in
[`track-d/crash-recovery.md`](../track-d/crash-recovery.md): 18/18 reviewed,
14 applicable Docker-free scenarios, and four worker/queue/hot-reload scenarios
inapplicable as worded. No worker or background queue is present; the API
publisher is synchronous and uses durable SQLite state plus explicit
reconciliation/replay. No exactly-once external delivery claim is made.

Historical V10-D evidence reports 14/14 applicable Docker-free cases. Master
V1 strengthened two local crash boundaries and clarified the publisher-process
analog name; the complete Docker-free crash test module passes 7/7 tests.
Remaining model limitations are:

- DCR-04 terminates at an injected `post` callback, not during a real in-flight
  HTTP exchange.
- DCR-01 now issues a signed API request, exits immediately before event
  persistence, verifies that no acknowledgment returned and no event exists,
  then accepts a fresh-nonce retry after restart.
- DCR-05 now uses a temporary local HTTP receiver that records the synthetic
  remote side effect and withholds its response; the publisher is interrupted
  and restart remains ambiguous without a second request.
- DCR-16 is explicitly named a publisher-process retry analog; it is not
  evidence of a worker, which does not exist.

The strengthened tests improve the API acknowledgment and receiver-side
acceptance evidence, but the 14/14 figure remains the reported set of
applicable Docker-free scenarios, not proof of Docker restart recovery or
all real network timing behavior. Docker-backed recovery is 0/14: Agent A
could not pass Docker access preflight, no recovery fault runner was executed,
and the V10-D scenario table is a plan rather than runtime evidence.

Exact Docker execution blocker: normal shell `docker info` is denied on the
socket. The authorized operator must pass the V4 preflight. Before any
recovery Docker run, the fault runner itself must receive independent review
and each fault case must specify setup, outcome, cleanup, and evidence
artifacts. The source-level review is now PASS, but did not review or authorize
a Docker fault runner. Do not start a competing disposable stack.
