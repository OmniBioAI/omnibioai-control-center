# Docker access report — V4

Repository: `omnibioai-control-center`  
Host expected by the qualification harness: `spark-c275`  
Source HEAD observed: `f37ce8c952f917f607e9923cbb47dda8b0406a7a`

## Current Codex shell context

Read-only local context observations:

- UID/GID: `1000(manish):1000(manish)`.
- Supplementary groups reported by `id`: `1000(manish),65534(nogroup)`.
- Docker socket: `/var/run/docker.sock`, mode `0660`, owner `65534:65534` (`nobody:nogroup`).
- `DOCKER_HOST`: unset.
- Docker CLI context configuration: `default` (client-side only).
- Local group database has `docker` GID 988 and lists `manish`, but GID 988 is not in this process's supplementary groups.
- A prior Docker API call in this shell returned permission denied. No repeated daemon access attempt was made for V4.

The previous successful V2 harness call ran via the explicitly approved execution tool with a `require_escalated` request. That is a different execution boundary and is not used here: V4 prohibits privileged escalation or sandbox bypass. Its runtime UID/GID, supplementary groups, effective Docker context/host, and daemon identity were not preserved in the evidence, so a full apples-to-apples identity comparison is unavailable. Docker daemon identity is unverified. Do not infer Docker access from local group membership or `docker context show`.

Result: `DOCKER_ACCESS=FAIL` in the current permitted non-escalated shell. No socket, group, context, or daemon configuration was changed.

## Authorized-terminal handoff

An operator already authorized for the DGX Docker daemon should run the existing reviewed harness from this repository root in that same normal operator shell (not via `sudo` and not after changing socket permissions):

```bash
id
stat -c 'mode=%a owner=%u:%g' /var/run/docker.sock
printf 'DOCKER_HOST=%s\n' "${DOCKER_HOST-<unset>}"
docker context show
docker info --format '{{.ID}} {{.ServerVersion}} {{.Architecture}}'
python3 scripts/discord-docker-qualification/run_qualification.py
```

Stop if the normal authorized shell cannot execute `docker info`; do not elevate or alter permissions. The current harness cleans owned containers before final output, so the diagnostic enhancement below is a prerequisite to diagnosing Redis from a future run: retain a redacted service exit/health summary and Redis-only logs in the run evidence before ownership cleanup, with cleanup and after-inventory still guaranteed independently. Review that harness change independently before execution. Do not retain application environment values or synthetic webhook material in diagnostics.
