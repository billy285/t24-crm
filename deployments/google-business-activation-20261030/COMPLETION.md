# Existing-candidate completion

This separate tool resumes the already-created, never-started Google configuration candidate after frozen V3 comparison rejected Docker's null-to-false `HostConfig.OomKillDisable` representation. It does not edit the frozen V3 tools or artifacts, create/remove containers, change Nginx, restore a database, perform OAuth, or contact Google.

The comparison exception is narrow: the saved and current original must contain an explicit null; the never-started candidate must contain an exact JSON boolean false. Integer zero, true, missing values and strings are rejected. After start, an explicit null is accepted only as exact equality to the original, with no canonicalization. All other configuration, environment, mounts, networks, source, schema, private boundaries and callback protections remain strict. Receipts contain actual runtime hashes, never the comparison view. This is not verification of live kernel OOM behavior.

The semantic basis is [Moby v27.5.1 create-time default initialization](https://github.com/moby/moby/blob/v27.5.1/daemon/daemon_unix.go#L363-L366) and its [unsupported-kernel null reset](https://github.com/moby/moby/blob/v27.5.1/daemon/daemon_unix.go#L459-L466). [Docker resource-constraint documentation](https://docs.docker.com/engine/containers/resource_constraints/#limit-a-containers-access-to-memory) describes OOM killing as enabled by default.

## Execution order

1. Independently review the new tool freeze and commit only the reviewed tools to an immutable carrier. The three frozen V3 modules always come from carrier `b37565afba522e26b2f5ded47d8aafc24237b028` with their original hashes.
2. Generate `audit`, `complete` and `rollback` wrappers with `make_completion_command.py --carrier <full reviewed tools commit> --phase <phase> --out <local path>`. The generator verifies the completion hash, local frozen files and committed bytes, then produces a wrapper below 8 KiB. No command executes a server locally.
3. Run the read-only audit in the authenticated Ali server context and independently review its receipt. The audit proves the exact false value, unchanged primary runtime, current protected callback configuration, staged six-key environment and the no-execution recovery source-reading protocol while the original remains running.
4. Run completion once. Before stopping the original, the tool records an immutable completion intent and audit under `attempt-v3/completion-oom-default`. It reuses the known candidate ID from the untouched V3 switch-state. Successful completion records `enabled.json` separately.
5. On failure or interruption, use only this tool's explicit `rollback` phase. Existing intent blocks a forward retry. Recovery checks the exact known IDs, original settings, source, schema, static files, private boundary and protected callback before mutation. It stops and retains the known candidate, restores/restarts the original and leaves every database row and credential file intact. Unknown primary/reserved-name occupants or schema/source drift stop recovery for manual review.

Do not use frozen V3 `enable` or `rollback` for this interrupted attempt. Their original semantics create/remove a candidate and do not contain this separately reviewed recovery path.

## Recovery source proof

The retained frozen inventory uses `docker exec`, so it cannot inspect a stopped original safely. The new read-only source proof instead reads fixed expected source files through Docker's local Unix-socket archive API, validates directory metadata via HEAD, rejects links and unexpected source additions, and hashes tar members in memory without extraction or execution. Data/log/credential directories are excluded. Each response allocation is capped, each request is limited to two seconds and the proof has a 30-second deadline. The audit exercises this exact protocol before any stop; the normal runtime source inventory is checked again after readiness.

Actual code review and synthetic tests do not establish that configuration activation or Google OAuth succeeded. Require the actual audit and enabled receipts, then browser authorization and read-only account/location verification separately.
