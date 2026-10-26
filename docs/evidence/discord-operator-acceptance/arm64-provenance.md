# ARM64 and image provenance result

Host observation: `spark-c275`, Linux aarch64. DGX Spark hardware identity is
NOT_VERIFIED. Docker CLI context: `default`. The authorized read-only runner
`python3 scripts/qualify_discord_v8.py --mode inspect --timeout 30` returned
Docker daemon permission denied, zero containers, no Docker server, and
`source_image_provenance=NOT_VERIFIED`.
The current Unix identity is `manish` and belongs to `nogroup`; the socket is
group-owned by `nogroup` with mode `srw-rw----`, yet the API call is still
denied in this session. This is consistent with an additional sandbox policy;
it does not establish the authorization of an operator outside this session.
No permissions were changed. No Compose projects could be enumerated.

| Requirement | Result |
|---|---|
| Host architecture | aarch64 observed |
| DGX hardware model | NOT_VERIFIED |
| Docker daemon / Compose projects | BLOCKED; daemon permission denied |
| Candidate image IDs and immutable digests | NOT_VERIFIED |
| Image architecture and build labels | NOT_VERIFIED |
| Source commit to image provenance | NOT_VERIFIED |
| Runtime config and secret references | NOT_VERIFIED |
| Persistent storage, health, logs, metrics | NOT_VERIFIED |

No socket permission, container, service, mount, or production configuration
was changed. Do not treat an aarch64 host observation or an image tag as image
qualification.
