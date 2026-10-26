# ARM64 image and source provenance

**Result: PARTIAL; source provenance NOT_VERIFIED.** Docker image inspection
is available. The V8 inspector found three Control Center records and passed
its ARM64/digest condition: inspected Control Center images are ARM64 and have
immutable repo digests. The running web image has repo digest
`sha256:ad11b3005f2625cc5d4b65cd38fd56c20e383190f78cd570c57dbe2f904f37eb`.

That image has no OCI source or revision label. No signed build attestation,
reproducible-build record, dependency-lock proof, or exact dirty-working-tree
to image linkage was available. Therefore the inspector correctly retained
`source_image_provenance=NOT_VERIFIED`. G9 cannot pass until candidate and
prior immutable digests are bound to exact source and reviewed build inputs.
Tags and architecture alone are insufficient. No protected image was rebuilt
or replaced.
