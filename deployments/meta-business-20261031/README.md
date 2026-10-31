# Meta business connection release — disabled initial deployment

This independent release adds owner-only Facebook Login for Business connection infrastructure, Page/linked professional Instagram discovery, per-customer bindings and disconnect. It does not enable publishing, comments, OAuth credentials, Meta fetches, provider actions or employee access. A later separately reviewed configuration step is required once the actual Meta application, version and access have been verified.

## Frozen baseline and scope

- Frontend `f3e9e6f7bfa0`, application `04a42942ce128f74c77db9250f2e7a28485b5c32`, backend `5931e430e629fb633f846ebc068a8fc12d4b9a0a`.
- Actual static deployment receipt `ece3827fd84049525823e672ad9b76288b929894d01b8f900c3e0c722c711200`; current Google scheduler remains ON with cutoff `2026-10-30T19:42:04Z`.
- Fresh, reviewed read-only production baseline: schema `acd7c9d0e136`, 136 existing tables. Existing Google tasks, LIVE actions, images, policies and leases are legitimate and may be nonempty.
- Exactly one additive migration `acd7c9d0e136` → `bde8da01f247` creates five empty Meta tables and the reviewed indexes. No seed rows, old-table alterations, changed business calculations, permissions, private workspace or subscription rules.
- All `T24_META_*` environment keys remain absent; original environment, Google credentials, mounts, network and private metadata remain exact.
- Nginx changes only one static root and adds an exact copy of the approved Google OAuth callback location for `/api/v1/meta-business/oauth/callback`. Existing Google callback, image delivery privacy, CSP and all other bytes remain unchanged.

## Review gates

`preflight.py` is immutable and already reviewed. It captures current table fingerprints and schema/metadata hashes on the exact host, without exporting row contents or credential material. The public summary and protected full proof are separately pinned. Only the previously observed `monthly_deduction_rates` counter may independently advance; every table row, schema, PRAGMA, sequence key and all other counters remain exact. Offline migration/startup must preserve metadata with no counter exception.

Application source, FE version and unified source freeze start unset in `release.py`. The package builder fails closed until final reviewed pins, exact migration shapes/indexes, routes and source/test allowlists are set. It accepts only the exact committed app delta and deterministic bounded static/runtime payload; no secrets, data, user photos or test files enter the payload.

`prepare` builds a local patch image from the exact existing image with network disabled. It backs up only to an isolated probe directory, runs the additive migration atomically against that copy, starts a read-only-root/network-none candidate with no provider credentials and all workers off, verifies Python 3.10, exact router provenance (including hidden image GET/HEAD), Meta disabled configuration, and all 136 original table rows/objects/metadata. It stages a new static root but does not activate it, migrate production or change Nginx.

After independent review of the actual canonical `prepared.json`, `activate` binds/fsyncs the exact candidate identity before stopping the original. It checks the fresh original boundary again, records a protected baseline, migrates production in one transaction and moves forward using only the prepared image. The new app must preserve every original business row and all five Meta tables must remain empty. It verifies unchanged Google ON/cutoff, absent Meta configuration, exact public version/readiness/CSP, invalid image-lease GET/HEAD privacy and an invalid Meta callback with no cookie or valid state. Sentinel checks scan only bounded new Nginx bytes and bounded candidate logs, exporting pass/fail metadata only.

Recovery never restores a database, rewrites counters, deletes production containers or guesses orphan IDs. Before migration commit it can resume the exact compatible original. After the new head commits, recovery is forward-only to the durably identified new image; legitimate independent rows are preserved. A failed acceptance contains the candidate if safe forward recovery also fails. A successful deployment requires separate review for any further recovery.

## Authoring and execution

Run focused tests with the project Python environment. Build the payload from the reviewed production summary using `build_payload.py --preflight-summary ... --out ...`; independently rebuild and compare every byte. `make_commands.py --carrier <immutable SHA> --preflight-summary ... --out ...` emits a prepare wrapper after all four committed members and the app tree match. Add `--prepared-receipt ...` only after the actual protected receipt has been independently reviewed; the generator then emits activate/recover wrappers bound to its canonical SHA. The generator never executes a phase. Production execution belongs to the parent workflow after exact wrapper review.

Do not reuse old deployment directories, replace failed staging, edit previous tools, add provider configuration, initialize tasks/policies/leases, publicly post content, or run the generated wrappers during local authoring.
