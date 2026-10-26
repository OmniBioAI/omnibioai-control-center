# Historical crash matrix dispositions — V4

Authoritative source remains `docs/evidence/discord-final/qualification.md`, Required process/crash case table. Preserve IDs DCR-01 through DCR-18. This matrix does not report execution passes.

| ID | Original scenario | Current synchronous contract disposition | Independent acceptance | Execution |
|---|---|---|---|---|
| DCR-01 | Crash before persistence | Applicable; determine request acknowledgement vs durable SQLite commit | Pending | Not run |
| DCR-02 | Crash after persistence | Applicable; durable row should survive API process restart | Pending | Not run |
| DCR-03 | Crash before HTTP submission | Applicable; persisted delivery state precedes synchronous HTTP submit | Pending | Not run |
| DCR-04 | Crash during submission | Applicable; in-flight request outcome may be ambiguous | Pending | Not run |
| DCR-05 | Remote acceptance before local receipt | Applicable; at-least-once/ambiguous external effect; exactly-once not assumed | Pending | Not run |
| DCR-06 | Restart with pending records | Applicable to durable pending/approval records, subject to code path | Pending | Not run |
| DCR-07 | Restart with ambiguous records | Applicable; no blind resend if contract marks ambiguous | Pending | Not run |
| DCR-08 | Concurrent worker claims | Not applicable as worded: no worker/claim queue; candidate synchronous analog is concurrent API access/SQLite state exclusion and requires accepted remap | Pending | Not run |
| DCR-09 | Duplicate event submission | Applicable; stable event ID deduplication | Pending | Not run |
| DCR-10 | Discord 429 | Applicable; synchronous retry/rate-limit metadata | Pending | Not run |
| DCR-11 | Discord 5xx | Applicable; retry/ambiguous-state handling | Pending | Not run |
| DCR-12 | Network interruption | Applicable; synchronous HTTP transport interruption | Pending | Not run |
| DCR-13 | Database interruption | Applicable; SQLite persistence interruption | Pending | Not run |
| DCR-14 | Dead-letter transition | Applicable only to implementation's local JSONL dead-letter behavior; not a queue DLQ | Pending | Not run |
| DCR-15 | Authorized replay | Applicable to IAM-protected replay endpoint | Pending | Not run |
| DCR-16 | Worker restart during retry | Not applicable as worded: no worker; possible API process interruption during synchronous retry is a distinct remap | Pending | Not run |
| DCR-17 | Configuration reload | Conditional; reload mechanism and durable behavior require source-contract confirmation | Pending | Not run |
| DCR-18 | Queue reconciliation after process termination | Not applicable as worded: no queue; stale SQLite delivery reconciliation is a separate contract | Pending | Not run |

Disposition count: 18/18 individually recorded, but **independent acceptance is 0/18**, applicable execution is **0/14**, and crash-recovery gate remains NOT_VERIFIED. The four cases DCR-08/16/17/18 are not counted as passes or silently replaced. An independent reviewer must accept each not-applicable/conditional rationale and any proposed synchronous analog before scenario remapping or gate closure.
