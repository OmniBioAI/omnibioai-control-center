# Master V1 auditable source snapshot

Base commit: `f37ce8c952f917f607e9923cbb47dda8b0406a7a` (`main`). The shared
worktree is dirty and is not represented by the commit alone. No commit or
staging was performed.

Current qualification runner source-tree digest (backend package plus
qualification harness):
`b7bf95c9f9bd1af4da8a2d90a7e325261a304f001781a453334e9fa8c27ec725`.
This differs from V11.6's reviewed digest because the master fail-closed
`notify()` correction changed backend source after the earlier independent
review and Agent A preflight. A fresh independent code-level review passed
against this current digest; it does not constitute Docker runtime
qualification or authorize execution without the operator preflight.

`git-source-snapshot.tsv` records Git blob IDs for the backend package,
backend tests, qualification harness, Docker build inputs, and relevant test
lock present in the current worktree (tracked, modified, and untracked files).
`source-inventory.sha256` records file hashes for those inputs and the Master
V1 evidence artifacts. Both exclude their own content to avoid self-reference.
Reproduction is the recorded base commit plus the exact listed content
overlay; unrelated files are not part of the listed source set.

Verify from repository root:

```text
sha256sum -c docs/evidence/discord-master-v1/source-inventory.sha256
sha256sum -c docs/evidence/discord-master-v1/SHA256SUMS
```

The root repository and sibling ecosystem repositories contain unrelated
dirty work. Those edits were preserved and are not claimed to be part of this
candidate. Because the repo's Git metadata is read-only here, the isolated
development branch is a temporary clone under `/tmp`; only the two reviewed
Control Center files were integrated into the shared workspace.
