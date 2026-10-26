# Rollback / first-release recovery — Master V1

`ROLLBACK=NOT_VERIFIED`. No compatible historical multichannel rollback image
or Docker-backed rehearsal is evidenced. The prior `v0.7.5` single-webhook
contract and recorded local images predate signed event ingestion, six-channel
routing, and SQLite event/reconciliation state; they must not be called a
compatible rollback target or mounted against upgraded candidate state.

Track F's recovery plan is properly classified as **first-release recovery**:
retain the exact legacy image/config/state baseline, make and restore-test a
consistent isolated backup, keep candidate state separate, and restore the
saved baseline if a first multichannel release fails. This procedure has not
been rehearsed and is not equivalent to a verified rollback gate.

Next action: after producing a reviewed immutable ARM64 candidate and a
disposable environment, test first-release recovery using synthetic
credentials and copied disposable state, verify the restored image/config/data
and health, and independently review the evidence. Do not modify production.
