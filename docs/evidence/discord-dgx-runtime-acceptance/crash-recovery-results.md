# Process crash-recovery results

**NOT_VERIFIED — 0/18 container scenarios.** Docker read-only access works,
but no reviewed disposable service harness, fault-injection contract, or
isolated candidate stack exists in the repository. No production or existing
process was signaled.

Fresh focused tests include seven passing local subprocess/SQLite cases with
mocked Discord transport. They do not substitute for the required Docker
matrix or prove exactly-once external delivery. The 18 documented cases are:
crash before/after persistence; before/during HTTP; remote acceptance before
local receipt; pending/ambiguous restart; concurrent claims; duplicate
submission; 429; 5xx; network and database interruption; DLQ; authorized
replay; worker restart during retry; configuration reload; and queue
reconciliation. Run them only against the reviewed disposable project and
record persisted state around every restart.
