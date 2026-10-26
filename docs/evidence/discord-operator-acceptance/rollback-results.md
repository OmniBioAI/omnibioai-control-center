# Disposable rollback qualification

`ROLLBACK=NOT_VERIFIED`. Docker daemon access is denied in this session, so no
candidate image or previous known-good digest could be inspected or run. No
disposable Compose stack, database, queue, or volume was created. No production
rollback was attempted.

Pending requirements for an authorized disposable stack:

- Record both candidate and previous immutable image digests and provenance.
- Create synthetic pending, approved, delivered, and ambiguous queue records.
- Switch only the disposable stack to the previous image.
- Verify schema compatibility, queue and ambiguous-state preservation,
  existing alerts compatibility, deduplication, health, metrics, and audit
  records.
- Keep ambiguous external deliveries from being blindly retried.

Acceptance requires persisted evidence from the disposable database and
service health/readback; image tags and in-process mocks are insufficient.
