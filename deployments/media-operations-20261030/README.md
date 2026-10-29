# Media operations first-phase release — 2026-10-30

This release is explicitly scoped to `d70c28dae860598229c7d81299d8a65db016f764`.
The production application baseline is `3eac5daaf881bc5398cfa67223485cf12cf9ff2c`, frontend `197e83470ec1`, schema `a8d4e2c6f901`.
The immutable carrier may contain these tools and artifacts but must have the identical application tree.

## Scope and invariants

- Exactly 19 changed application files: 5 backend runtime files, 13 frontend files and one backend test. The publisher pins the exact list; the builder also compares every other tracked application file.
- Backend overlay: `routers/app_config.py`, `routers/media_operations.py`, `services/media_operations.py`, `models/media_operations.py`, and `alembic/versions/b7c2d9e4a601_media_operations.py`. Original financial handlers, role enforcement, customer grants and private modules are excluded.
- Upgrade `a8d4e2c6f901` → `b7c2d9e4a601` creates **only two empty tables**, `media_operation_tasks` and `media_operation_events`, with five named indexes. SQLite internal auto-indexes are excluded consistently by the retained schema inventory. Every original schema object remains identical.
- **No existing-row exception except the exact Alembic revision.** App settings, employees, grants, financial rows and old finance-entry drafts/evidence remain byte/value identical. Versioned default navigation adds the authorized media page; persisted role config is not rewritten.
- No employee, task or content seed; no platform publishing, provider writes, billing action, policy enablement or original ledger writes. No dependency installations.
- No private runtime restart, secret rotation, mount, network or environment change. The new CRM container clones the current configuration; image/hostname/release labels are the only normalized differences.

## 1. Fresh authenticated read-only baseline

From the repository root, generate locally:

```sh
python3 deployments/media-operations-20261030/generate_preflight_command.py
```

The owner runs the resulting `preflight-command.sh` through the already authenticated server console. It fixes the host/root, retained helper and private-boundary proof hashes; checks current frontend/schema, source inventory, database identity, read-only table fingerprints, `/ready`, original static files and private runtime twice. It does not execute a provider request, mutation or restart, and emits only counts/hash metadata. It neither exports raw customer rows nor reads credential values.

Save the output envelope, verify its declared proof size/hash, decompress its `proof_zlib_base64`, and save the exact canonical proof bytes as `preflight.json` in this directory. Never reconstruct financial row data. A baseline drift must stop and be reviewed, not bypassed.

Required server inputs are only that fresh proof and the already pinned retained-helper/private-boundary files. No password, JWT, API key or production database copy should be supplied locally.

## 2. Local checks and packaging

Use the existing isolated Python environment; no production DB/provider:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/experience-python/bin/python -m pytest -p no:cacheprovider -q deployments/media-operations-20261030/test_release.py
```

Root separately runs the existing 50 media workflow/permission/concurrency tests and frontend verification, builds the exact committed frontend and records its version. The release-tool tests run the actual migration on synthetic SQLite, prove transactional rollback and unchanged app settings/financial/account/grant rows, attack manifest/DDL/runtime boundaries, inspect real `main.app` without DB/network/lifespan and reject lazy-router duplicates or extra methods. No PostgreSQL concurrency claim is made by this publisher.

Package from repository root after final source/build verification:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/experience-python/bin/python deployments/media-operations-20261030/build_payload.py --source d70c28dae860598229c7d81299d8a65db016f764 --preflight deployments/media-operations-20261030/preflight.json --out deployments/media-operations-20261030/artifacts
```

This is a local artifact operation, not a build or deployment. It requires the committed source and working files to match, refuses uncommitted frontend source, derives exact migration objects on synthetic SQLite, pins all safe static members and excludes secrets, databases and seeds. Output targets must be fresh.

## 3. Immutable carrier and prepare

After independent package review, root commits/pushes the exact tools/manifest/payload in a carrier with unchanged application tree. Generate local commands:

```sh
python3 deployments/media-operations-20261030/make_commands.py --carrier FULL_CARRIER_SHA --preflight-receipt deployments/media-operations-20261030/preflight.json --out deployments/media-operations-20261030/commands
```

Only `receipt-install-command.sh` and `prepare-command.sh` are produced at this stage. The former installs the canonical read-only proof as a protected root-only file; it does not modify app config or DB. The latter downloads three exact SHA/size-pinned members from the full immutable carrier URL, refuses redirects and existing staging, and executes only the pinned publisher.

Prepare backs up the business DB to a root-only isolated copy, creates a network-disabled candidate from the exact current image with only the five reviewed files overlaid, applies the additive migration to that copy, and disables both Stripe workers. No credential file or private DB is mounted into the offline candidate. Actual Python 3.10 startup and all **six** media route methods must pass OpenAPI plus canonical `iter_route_contexts` count/set/module checks (old flat route fallback only when the canonical API is absent). All seven supported business timezones must resolve through the candidate Python `ZoneInfo` implementation without network access. Every original copied row must remain unchanged; both new tables must stay empty. Static staging preserves old hashed assets. Prepare rechecks the unchanged production boundary before returning the hash-bound receipt. It never stops production or migrates its DB.

## 4. Actual prepared review and activation

Only after independent review of the actual canonical `prepared.json`:

```sh
python3 deployments/media-operations-20261030/make_commands.py --carrier FULL_CARRIER_SHA --preflight-receipt deployments/media-operations-20261030/preflight.json --prepared-receipt deployments/media-operations-20261030/prepared.json --out deployments/media-operations-20261030/commands
```

Activate/recover commands now bind the exact receipt/helper/payload/source hashes. Root executes activate through the authenticated console. Publisher revalidates current rows/schema/runtime/private/static boundary, stops only the original CRM, makes a verified backup, commits the two-table migration and Alembic head atomically, proves all original rows/schema unchanged, retains the stopped old container, starts the exact reviewed candidate, proves its full source inventory and normalized runtime, then changes only the Nginx public root by compare-and-swap. Public frontend version/readiness and final DB/runtime/private proofs must pass.

## Failure and acceptance

- Nothing is deleted and the DB is never automatically restored. After any migration, recovery uses the reviewed **new** image only. The original application may resume solely if no migration/candidate work occurred and exact old schema/runtime still match.
- Interrupted activation uses only the generated hash-bound `recover-command.sh`. A successful release is not automatically recovered or rolled back.
- A failed prepare is preserved. Do not remove staging or weaken a gate; diagnose first and independently review any evidence-preserving archive/retry command.
- Parent performs production GET-only browser acceptance after deployed proof. Live task/account creation, publishing, billing and credential actions are outside release acceptance.
