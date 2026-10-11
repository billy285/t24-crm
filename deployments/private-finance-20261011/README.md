# Private banking / Stripe / owner brief joint release preparation

Status: release tooling prepared only. No final payload or frozen source manifest, no production credentials, bank authorization, real data acceptance, push or deployment is implied.

## Scope and known baseline

The owner authorized connecting real Bank of America balances/transactions and the private PIXELPATE Stripe account, then publishing together with the prepared owner brief. This is an independent owner-only workspace. Customer finance calculations and customer CRM records remain separate. Bank email alerts are not acceptance of direct bank balances or complete transactions.

On 2026-10-11 a no-credential request to the public `app-version.json` returned `54da68143ed2`, matching the saved responsive static release (`30d9748`). Saved private service receipts reference `dd8061c`, image `sha256:2ed347b29ba8f29ffeaab26df75e8c5d75c7479b477a1e45e80bdf2b19d098db`, API `31b4553486ac7955733877db576655648ed9cc778a153dc5591958831298020f`, worker `bbbb2c880eb7246fc98f9704d7cdb306541bb989b297cbf1e6381c22229095da`, and four private tables. These are saved evidence, not a freshly authenticated server inspection. Reconcile all live identifiers, configuration hashes, mounted paths, active static directory, owner/session status and schema before preparing a final candidate.

The customer service is separately bound to loopback 8000; the private API is bound to loopback 8001. Preserve the CRM container, start time, configuration, image and customer database. Never invoke the CRM lifespan, business migration or financial jobs from the private candidate.

## Obsolete scripts

Keep historical deployment files unchanged. The initial `private-workspace-20261011/deploy_private.py` creates the original installation and is unsuitable for upgrading it. The old Ads payload collects only three service files. Its switch requires exactly four private tables and an unchanged whole-schema hash. It cannot publish the nine-table brief candidate or a future additional bank table. Do not replace its inventory constant and silently bypass that rejection.

Build a new payload from the final reviewed SHA after bank and Stripe implementation finishes. Collect the exact complete private backend delta, all required private tests and the complete new frontend build. Verify the candidate backend tree against the baseline: unrelated customer services and runtime package bytes must remain unchanged. Freeze the source SHA, built frontend version, archive/file hashes, candidate image identity and test evidence together.

## Read-only migration guard

`private_schema_guard.py` never executes DDL, writes a database, reads environment credentials or starts/publishes services. Its snapshots use SQLite URI `mode=ro`, `query_only`, a consistent read transaction and `integrity_check`. Receipt data contains only hashes, counts, file identity and schema metadata; no mail, bank record, stored credential, amount value or SQL text is emitted.

It supports **only a freshly verified original four-table baseline with an explicit additive target**. The actual nine-table model schema and ten-table schema including `private_bank_links` are exercised by the synthetic tests. The tenth bank table is accepted only when an independently reviewed frozen manifest lists its exact table/index DDL hashes; an unexpected table is rejected. Six/eight-table intermediary baselines require a separately reviewed migration policy. In particular, the prior USD budget migration is not silently treated as a rows-preserving additive change.

Freeze private writers before the production before-snapshot. Back up the original private database using SQLite's backup API to a root-owned directory mode 0700/file mode 0600; verify backup integrity, private-only inventory, owner 4, rows/columns/indexes and encryption configuration identity. Do not copy database contents or secrets into a public output, Git archive, browser bundle or log. Do not chmod the customer database or a shared directory to satisfy this tool.

First run the candidate initializer on that isolated private copy with network disabled, a synthetic/nonproduction identity reader, AI disabled, no worker and no production credential loaded. Build `target_schema_objects` from a separate empty candidate schema, not from the migrated production database. Review and freeze the manifest before validation. Every original four-table row, column, DDL and index must survive unchanged. Every added table must be empty until schema acceptance; perform bank/Stripe connections and start syncing afterward.

Required frozen manifest shape:

```json
{
  "format_version": 1,
  "stage": "FROZEN_PRIVATE_ADDITIVE_SCHEMA_MANIFEST",
  "source_sha": "REPLACE_WITH_REVIEWED_FINAL_40_HEX_SHA",
  "baseline_tables": ["private_connections", "private_items", "private_preferences", "private_sync_runs"],
  "target_tables": ["EXACT_REVIEWED_PRIVATE_TABLE_INVENTORY"],
  "target_schema_objects": {
    "EXACT_TABLE_OR_INDEX_NAME": {"type": "table", "table": "EXACT_PRIVATE_TABLE", "sql_sha256": "64_HEX_SHA_OF_CANONICAL_SQL_VALUE"}
  },
  "business_table_count": 83,
  "business_schema_sha256": "FRESH_64_HEX_CUSTOMER_SCHEMA_HASH"
}
```

This illustration is deliberately invalid and cannot authorize a release. Save exact manifest and snapshot bytes under protected release storage and pass their reviewed SHA-256 values to `validate`; the tool refuses source/manifest/receipt drift. `snapshot` creates a new exclusive receipt. `validate --mode clone` proves the rehearsal has a distinct file identity. `validate --mode in_place` additionally requires the original production private file path/device/inode remain unchanged. Neither mode applies a migration.

Example commands (placeholders must be resolved by the release operator):

```sh
python private_schema_guard.py snapshot --private-db /absolute/protected/private.db --business-db /absolute/customer.db --output /absolute/protected/before.json
python private_schema_guard.py validate --before /absolute/protected/before.json --before-sha256 REVIEWED_BEFORE_SHA256 --after /absolute/protected/after.json --after-sha256 REVIEWED_AFTER_SHA256 --manifest /absolute/protected/frozen-schema.json --manifest-sha256 REVIEWED_MANIFEST_SHA256 --source-sha REVIEWED_SOURCE_SHA --mode in_place --output /absolute/protected/validation.json
```

## Runtime and credential boundaries

- Both private processes mount the customer identity directory physically readonly and use a SELECT-only identity connection. Preserve live, revocable employee-session checks and owner employee 4. Neither process may mount customer data writable or expose its port publicly.
- Private credentials are private-service-only. Use a dedicated Stripe restricted key for the confirmed private account and verify its actual permitted resources. A `rk_live_` prefix is not evidence that its configured permissions are readonly. Do not reuse a customer CRM Stripe key.
- The revised Stripe adapter uses the encrypted independent-DB credential after connection; its synthetic regression verifies worker reads without `PRIVATE_WORKSPACE_STRIPE_KEY`. The dedicated restricted key is needed only by the private API during initial connection. Preserve confirmed Stripe account/mode configuration on API and worker and verify actual readonly permissions in the provider before acceptance. Do not load the customer CRM Stripe key into either private process.
- Split API and worker configuration files. OpenAI/translation keys belong only to the API workload, never the sync worker. Preserve owner encryption and JWT identity material; do not regenerate them during an upgrade.
- AI stays disabled by default: `PRIVATE_MAIL_BRIEF_ENABLED=false`, `PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT=false`, `PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED=false`, `PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT=false`. Bank/Stripe/local brief deployment may proceed independently of AI activation. The current Hong Kong host must not call OpenAI directly; actual activation needs an eligible account and legitimate supported-region deployment. The approved USD 5 API cap does not authorize new hosting spend.
- Bank OAuth/link credentials must remain private and encrypted. No account numbers, owner names, tokens, webhook secrets or raw financial events in payloads, logs or release receipts. Integration account identity may be checked in authenticated UI; save only controlled identifiers/hashes in release proof.
- Plaid defaults disabled (`PRIVATE_WORKSPACE_PLAID_ENABLED` absent/false). Actual activation requires the owner's consent to the provider product and applicable fees, a production-approved Plaid account, and credentials stored only in the private service. `PRIVATE_WORKSPACE_PLAID_ENV` defaults to `production`; explicit `sandbox` must stay visibly test data. Both private API and sync worker require the confirmed Plaid client/secret, environment and optional exact Bank of America institution binding. API initializes only the Transactions product and Hosted Link; no email/SMS/webhook delivery and no extra paid `/accounts/balance/get` or `/transactions/refresh` calls.
- Local disconnect clears credentials and pending sessions; the read adapter never invokes `/item/remove`. Plaid Transactions may remain subscribed after local disconnect. Resolve provider-side revocation/subscription cleanup with the owner in the Plaid dashboard before discarding a live Item. A repeat begin reuses a valid encrypted short-lived session; an active exchange is leased and cannot create another Item.
- Bank `/accounts/get` balances are cached provider values, not realtime bank balances. Preserve null values, separate accounts/currencies and positive credit/loan balance as debt. Decimal amounts convert with the verified ISO 4217 minor units from SIX List One (published 2026-09-17); unknown/no-scale currencies remain without a numeric minor amount. Full transaction pagination, pending replacement and removed-status updates commit atomically with the cursor. No first-page partial result is saved after a later-page failure.

## Ordered switch and acceptance

1. Authenticated readonly live baseline, owner 4 checks, customer schema/table fingerprints and private rows/DDL proof.
2. Complete source manifest, unchanged dependency proof, candidate-image private regression suite with network disabled and no production data.
3. Verified private backup; rehearsal migration and explicit frozen-schema validation; actual retained old image must start and read the upgraded synthetic/copy schema for rollback compatibility.
4. Stage new private API/worker without starting them. Preserve original containers, images and public assets. Refuse name collisions or baseline drift.
5. Stop only old private worker then API. Take frozen before-snapshot. Apply the reviewed private initializer in place; customer DB stays readonly. Start new API first; validate schema/row/index preservation and readiness before new connectors/worker.
6. Complete real bank and PIXELPATE Stripe authorization with the owner's help where needed. Verify source identity and successful first sync; balance/transaction coverage, pagination, pending versus posted states, currency separation, refunds/disputes/payout semantics, source time and reconnection/disconnection. Bank mail fallback remains explicitly unverified. Do not trigger payments, refunds, ad changes or customer ledger writes.
7. Start private worker; retain user overrides, stored connections, credentials/generations and stable item keys while permitting documented fresh sync data changes. Check no restart loop.
8. Publish matching static assets only after backend readiness; inspect desktop/mobile real UI, owner-only/sales denial, revoked-session denial, current asset graph/version/cache behavior and brief source states.
9. Compare customer service identity/configuration and all original customer fingerprints/schema before and after. A legitimate concurrent customer write requires investigation; never silently waive a mismatch. Record controlled hashes, counts, success/failure codes and actual limitations.

Rollback restores only the old private image/containers and prior static directory. Do not restore, overwrite or delete either live database as an automatic rollback. Preserve the upgraded private data and new bank/Stripe authorizations; verify the retained old image against the upgraded schema before the switch. An untested rollback is a release blocker.

## Candidate preparation, before any switch

`candidate_prepare.py` consumes independently frozen source, payload manifest, archive and authenticated live baseline files, each with its separately reviewed SHA-256. The live baseline is checked again before and after preparation. A previously saved baseline is never treated as proof that the server still matches. Keep these files mode 0600 under protected storage and use an unused `/opt/t24-crm/releases/private-finance-SOURCE12-20261011-candidate` directory.

The recipe derives only from the pinned retained private image. It copies the complete private backend delta, all private regressions and the complete frontend build. Candidate preparation compares all other backend file bytes and runtime package bytes with that exact image. It also checks the complete frontend build while preserving previously served hashed asset URLs. An existing hashed asset name with different bytes blocks preparation. Base image inspection stays in memory; a baked credential prevents isolated testing.

All candidate containers have network disabled, a readonly root filesystem, no production configuration, no published ports, no privileges and bounded resources. Writable mounts are confined to the new release's synthetic fixtures and test evidence. Only independently hash-verified pinned test wheels may be read from the retained release. The operator must first inspect/freeze the original `test-wheel-manifest.json` hash; preparation refuses a guessed or stale hash. Tests must include every frozen private test, meet the reviewed regression count and have no failures, errors or skips.

The schema rehearsal first creates a fictional original four-table database using the actual retained old image and seeds all four tables. An independent empty candidate database supplies the exact ten-table/index manifest before migration. The candidate initializer then upgrades a distinct synthetic clone. `private_schema_guard` requires every original row, column and index to remain identical, every new table to be empty and the fictional customer finance sentinel to stay unchanged. Finally the old image initializes and decrypts/reads the upgraded clone; another snapshot must prove this rollback rehearsal changed nothing. A synthetic manifest contains a synthetic customer schema hash: before a real switch the operator must independently freeze a production manifest with the authenticated 83-table customer schema and the candidate's proven private schema objects.

`candidate.json` is emitted only after all checks succeed and is explicitly `deployed=false`. This command does not stop, replace or start production services, migrate either live database, publish public assets, connect real accounts or activate AI. It leaves existing images and containers intact, and cleanup can remove only its own generated isolated container with the matching image and ownership label.

```sh
python candidate_prepare.py --freeze /absolute/protected/frozen-source.json --freeze-sha256 REVIEWED_SOURCE_MANIFEST_SHA256 --manifest /absolute/protected/private-finance-manifest.json --manifest-sha256 REVIEWED_PAYLOAD_MANIFEST_SHA256 --payload /absolute/protected/private-finance-payload.tar.gz --payload-sha256 REVIEWED_PAYLOAD_SHA256 --baseline /absolute/protected/live-baseline.json --baseline-sha256 REVIEWED_BASELINE_SHA256 --test-wheel-manifest-sha256 REVIEWED_RETAINED_WHEEL_MANIFEST_SHA256 --release /opt/t24-crm/releases/private-finance-SOURCE12-20261011-candidate
```

## Local verification

Run `python -m unittest discover -s deployments/private-finance-20261011 -p 'test_*.py' -v` using the prepared backend dependency runtime. Tests build the real current private model's original four-table schema, seed fictional credentials plus a customer finance sentinel, add the five current tables and validate unchanged original contents/indexes. Negative cases cover row/column/index drift, customer sentinel change, database alias, wrong owner, inode replacement, symlink/exposed permissions, unknown tenth table, early added-table writes and stale/unfrozen manifests. All writes are temporary synthetic fixtures.

Prepared local tooling validation: **15 tests passed**, including the actual CLI snapshot, four-to-nine migration, four-to-ten bank schema and frozen-hash validation. Bank provider/session/core delta regression: **59 tests passed**, using only MockTransport and temporary private databases, including date-only transaction ordering before the SQL record limit. Final production source, payload, frozen live manifest, bank/Stripe account authorization, actual candidate-image tests and deployed acceptance remain for the root release operator.

Candidate preparation has an additional **15 synthetic tests** for frozen scope, safe archive extraction, dependency/static byte preservation, exact test wheels, regression counts and Docker isolation/owned cleanup. These local tests mock Docker; they do not certify an actual candidate image, actual old-image rollback compatibility or a real deployment.
