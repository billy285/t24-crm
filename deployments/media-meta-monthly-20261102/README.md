# Facebook / Instagram merchant-month workflow release

This additive release reuses the existing owner-only merchant-month workflow and native Meta draft / schedule models. Google remains the default for historical run snapshots. No database migration, role grant, credential grant, provider call, financial change, private-space change, or production seed is part of the release.

Preparation and publication are separate. Internal monthly review may create native drafts and prepared schedules. Prepared schedules do not run. The existing Meta execution and scheduler switches remain false; original activation cutoffs remain exact. Public execution requires a later explicit owner confirmation and all existing native capability / account / image / current-copy / time-window checks. A read-only account connection never grants Meta operations access.

## Baseline and capture

The parent is the completed `media-operator-queue-20261102` release, application `e0f39295a912ac6f7518d523a860ee9ca649d54e`, frontend `04e77e374e74`, schema `g32ed456e792` with 162 populated tables and 419 runtime backend files. The fresh capture validates the parent's immutable helper, canonical prepared / deployed receipts, image, static tree, Nginx / CSP, environment hashes, credential metadata, private boundary, schema and per-table row hashes. It reads no credential or private file contents and performs no provider request. Its only write is a new root-private aggregate proof.

Generate and inspect the capture locally with `make_capture.py`; only the reviewed capture wrapper may be run on the exact authorized server. Keep the returned bounded envelope in `preflight.json`. Capture failure is fail closed, not permission to skip a baseline check.

## Source freeze and carrier

`release.py` and `build_payload.py` remain unusable until an exact committed application tree, fresh preflight and reviewed build are frozen with `freeze.py`. Packaging compares every application path against the live application's source commit, permits only the explicit runtime / frontend / test allowlist, hashes the exact local source and reviewed build, and creates a deterministic payload. The one new backend runtime module must be absent in the baseline and brings the candidate inventory to 420. No migration, dependency, environment, credential, tests or source maps are carried into runtime.

Commit the carrier only after the final application commit. `make_commands.py` checks that the carrier has that identical application tree and emits immutable commands. It never executes them.

## Prepare, activate, recover

1. **Prepare:** download only four exact hashed carrier members into a fresh root-private directory; copy the current SQLite database into an isolated probe directory; build only from the pinned existing image with network off and no dependency install; start a credential-free, network-none, all-workers-off candidate; verify routes, role denials, month / platform safeguards and existing boundary canaries; stop it; require all 162 copied table rows, metadata and schema unchanged; stage static assets. Production database and runtime remain untouched.
2. **Review:** verify and retain canonical server `prepared.json`; a transport envelope is not the review receipt. Compare exact source, image, static, schema, private / credential / environment and offline guarantees before generating switch commands.
3. **Activate:** re-check every live baseline and exact prepared image; durably record the new container identity before stopping the original; preserve original full configuration / secret mount / worker policies; replace only the Nginx static-root bytes; verify public version, OAuth / image-delivery privacy sentinels, CSP and all 162 table hashes unchanged. No public content is posted or armed.
4. **Recover:** contain only the known candidate, retain it stopped, restore the original name / static root and resume the exact compatible original. Never restore the copied database, delete production containers or execute a stopped ancestor. Independent rows remain intact.

A deployment receipt proves application deployment and the listed invariants. It does not prove a real Facebook / Instagram publication, active provider write authorization or user acceptance. Those remain separately verified and owner-confirmed.
