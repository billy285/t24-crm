# Sales note template guarded retry

This is an independent release attempt. The previous frozen helper, preparation,
activation and rollback evidence remain intact. App source stays
`f96eaa209f2d795efb6f5d780bf54b144a6ee380`, frontend `ebdd4929c921`, payload SHA
`9fd341069e77b2ba2146831b7fbf4fcb0acbb949420205630bf7dc735d6a4b3c`.

The reviewed failure mechanism is nondeterministic ordering of the complete Docker
`Mounts` array. This helper sorts those complete records by canonical JSON before
hashing. It preserves every mount property and duplicate. Config, HostConfig,
network fields, Env/Cmd and other list order, image, ID, start and restart fields
remain guarded exactly as before. No service, environment or DB mutation occurs.

Before freezing the carrier, capture the matching algorithm's full canonical CRM
runtime from authenticated read-only stable samples and independently review it.
The reviewed canonical SHA is `04d335218786997a6b9a7d2741fe485b1f03af8d8e5cceb24905cb049d287f61`,
pinned after ten stable healthy samples confirmed only raw mount-order variance.
Confirm no lifecycle change, unchanged old nginx/static version, unchanged
private roles/environment and both database identity/schema/columns, and retained
rollback evidence from the prior attempt.

Run `build_payload.py --source f96eaa209f2d795efb6f5d780bf54b144a6ee380 --out
deployments/sales-note-templates-retry-20261014/artifacts`. It retrieves the original
reviewed manifest/payload from immutable carrier `866320ba65b896193df895bda1dd1165aa47f6a2`,
verifies every source/static member and keeps the payload exact. The new manifest
adds only explicit retry/runtime-guard provenance. Current tracked/working app bytes
must still match that source commit.

Run local guard tests and review/commit the retry helper/artifacts as a new carrier.
Generate commands with `make_commands.py` against that carrier and the original
reviewed private pins. Prepare under a fresh `sales-note-templates-retry-<source>-20261014`
release/public root, review exact compact receipt bytes, then generate activation
with `--prepared-receipt`. All original static CAS, public asset/version, private,
compact database and recovery guards remain. Failed activation restores only the
prior static root and never restores business data.
