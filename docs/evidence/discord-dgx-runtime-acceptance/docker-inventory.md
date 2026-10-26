# Docker host inventory — authorized read-only execution

Date: 2026-10-24. Host: `spark-c275`, Linux `aarch64`. Docker context:
`default`; server `29.6.2`; architecture `aarch64`; daemon ID
`b94b0650-ebf7-4bc7-a57c-858b374141c7`. The permitted execution mechanism
returned the same identity twice and completed all later read-only calls. No
socket/group permission change, OS privilege escalation, or sandbox bypass was
attempted.

`python3 scripts/qualify_discord_v8.py --mode inspect --timeout 30` reported
`host_image_inventory_status=PASS`, `control_center_containers_found=3`, no
Docker errors, `production_mutation_performed=false`, and
`source_image_provenance=NOT_VERIFIED`. It exits 1 because its overall
`qualification` remains `NOT_VERIFIED`, not because Docker access failed.

The three Control Center records were
`omnibioai-studio-control-center-web-1` (running),
`omnibioai-studio-control-center-1` (exited), and
`37d9b2c754e6_omnibioai-studio-control-center-1` (created). The running web
container belongs to project `omnibioai-studio`, service
`control-center-web`, and network `omnibioai-studio_default`; it has no mounts
and publishes only `127.0.0.1:5174`. Runtime image ID:
`sha256:eed56e7615910e0501cf33fc2d0e1152ac0e398411dc6c3484aeaa8a39e1008c`.

Two consecutive normalized snapshots were identical:

| Resource | Count | SHA-256 of sorted IDs/names |
|---|---:|---|
| Running containers | 89 | `fb3119e4fe104172d27f41aa003340f50ff0569bea5dd4785cc8060e97d4d3bb` |
| All containers | 178 | `b710d95bb2ae3993d67147686e5be1950986dad07fb39b8a20cdc3ec7792e41b` |
| Networks | 39 | `724cd68eb3c3490d13d4e637955a7be6c3fbf30a42f8aa0aa3905ad159ffe9f5` |
| Volumes | 13,241 | `45b243ee344530231a69c0e8038c57be2f53a0683e3bb7fd653039743fe5c8c4` |

No container, network, or volume containing `discord` or
`dgx-runtime-acceptance` existed before or after qualification. No existing
resource was stopped, restarted, created, removed, pruned, or altered. This
proves this run left the existing inventory untouched. It does not prove a
Docker E2E isolation boundary because no disposable stack was launched.
