# Google Business disabled/unconfigured release — 2026-10-30

This publisher supports only the **disabled, unconfigured** CRM rollout. It cannot provision Google credentials, enable Google API access, authorize OAuth, bind a live merchant or make a Google request. The Cloud API quota was not approved when this release was prepared; Google project provisioning and OAuth activation are a separate future review.

The application baseline is `d70c28dae860598229c7d81299d8a65db016f764`, frontend `dcebcd11552a`, schema `b7c2d9e4a601`, image `sha256:e4ea5e98a8f9598ab24625df2b7f9756f595b7f887416a76ed4538394c1be033`. The prior actual deployed receipt is `813d64b72eab69ea623b164af1ad82e4c7890c8e8b611a277b304f8feff1d10c`. The reviewed application source is `7431d1986b81328fcc822e3e13641e4d03b6b9bf`, frontend build `c648c284143e`, pinned in `release.py`. No other source may be packaged.

## Exact scope

- Exactly twelve application files: six backend runtime files (five new Google files including migration plus `services/media_operations.py`), five frontend files and one new synthetic test file.
- Add five empty tables: `google_business_connections`, `google_business_oauth_states`, `google_business_bindings`, `google_business_grants`, `google_business_actions`, plus seven named indexes. SQLite automatic indexes remain consistently excluded from DDL inventories.
- Upgrade only `b7c2d9e4a601` → `c8d3e5f6a702`. Every existing table, schema object and row is preserved except the exact Alembic revision. This includes both original media tables, finance rows, employees, all customer grants, app settings, role configuration and prior finance-entry records.
- All original 119 tables are fingerprinted by a fresh read-only preflight. Prior release runtime, schema, exact backend inventory, static files and Nginx must still match. Legitimate business rows are captured fresh rather than assumed unchanged since the previous deployment.
- No package install, account/task seed, provider request, private database mount, credential reading/export, role repair, external publishing or Google access enablement.
- Any `T24_GBP_*` environment name is rejected, including `T24_GBP_ENABLED=false` or an empty value. Runtime configuration is cloned unchanged; the implementation's actual disabled default is tested instead of adding an environment override.

## 1. Authenticated read-only preflight

Generate locally:

```sh
python3 deployments/google-business-20261030/generate_preflight_command.py
```

Run `preflight-command.sh` through the owner's authenticated Alibaba Cloud command console on the exact pinned server. It only obtains read-only counts/hash metadata, not financial/customer records. Verify the returned envelope length and SHA, decompress `proof_zlib_base64`, and save the **exact bytes** as `deployments/google-business-20261030/preflight.json`. A drift or configuration presence stops the release; do not bypass it.

## 2. Source, tests, build and package

Root supplies a final immutable application commit and pins `SOURCE_SHA` in the publisher after reviewing exactly twelve changed application paths. No mutable branch or uncommitted source is accepted. Run:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/experience-python/bin/python -m pytest -p no:cacheprovider -q deployments/google-business-20261030/test_release.py
```

Root independently completes the Google workflow/security tests, original media/customer/financial-access regressions, frontend behavior checks, and exact committed production build. The publisher tests run actual additive migration/rollback on synthetic SQLite; verify every old row and object; attack manifest/file/scope/environment gates; import actual FastAPI without DB/network/lifespan; prove all eighteen Google and six retained media methods and endpoint modules; and prove actual disabled/unconfigured Google settings without provider/network access.

Package only from the reviewed source and fresh canonical preflight:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/experience-python/bin/python deployments/google-business-20261030/build_payload.py --source FULL_REVIEWED_SOURCE_SHA --preflight deployments/google-business-20261030/preflight.json --out deployments/google-business-20261030/artifacts
```

This does not build or deploy. It checks every tracked application file, exact twelve-path diff, working tree, frontend source inventory and build-version identity. It derives migration objects from synthetic SQLite, pins all safe payload members, excludes databases, secrets and seeds, and refuses existing output artifacts.

## 3. Immutable carrier and isolated prepare

After independent package review, commit/push exact publisher, manifest and payload in an immutable carrier with identical application tree. Generate only install/prepare commands initially:

```sh
python3 deployments/google-business-20261030/make_commands.py --carrier FULL_CARRIER_SHA --preflight-receipt deployments/google-business-20261030/preflight.json --out deployments/google-business-20261030/commands
```

The receipt installer writes a root-only proof file only. Prepare downloads exact size/SHA-pinned files from the full immutable GitHub carrier URL, refuses redirects/fresh-staging drift and executes only the pinned publisher.

Prepare builds offline from the exact existing image with the six-file overlay. It migrates only an isolated verified DB backup, using `BEGIN IMMEDIATE` for failure-atomic DDL. The candidate has network `none`, disabled Stripe workers and no new credential/private mounts. Actual Python 3.10 startup, all eighteen Google plus six media routes, seven business timezones, unchanged old rows, five empty new tables and **actual `enabled() is False`, exactly six missing Google settings and empty dedicated credential values** must pass. Production remains running and unmigrated during prepare.

## 4. Actual prepared review and activation

After independently reviewing the actual canonical `prepared.json`:

```sh
python3 deployments/google-business-20261030/make_commands.py --carrier FULL_CARRIER_SHA --preflight-receipt deployments/google-business-20261030/preflight.json --prepared-receipt deployments/google-business-20261030/prepared.json --out deployments/google-business-20261030/commands
```

Activate/recover now bind that exact receipt and source/helper/manifest/payload hashes. Activation revalidates fresh original rows/runtime/schema/static/private/credential metadata, retains the original stopped CRM container, backs up and atomically adds the five empty tables, proves no old row changed, starts the reviewed new image using cloned original environment/network/mount configuration, and changes only Nginx's public root by compare-and-swap. It verifies public readiness/version and reruns the actual disabled Google configuration probe in the running candidate. No Google environment or credential variable may be introduced.

## Failure and acceptance

- Failed staging is preserved for diagnosis; do not delete or weaken a gate.
- No database restore and no old-code startup after migration. Interrupted activation uses the generated hash-bound forward recovery command and the reviewed new image only.
- Root independently reviews the actual deployed receipt and performs production read-only desktop/mobile UI acceptance. No live account creation, grant change, OAuth authorization or Google publishing is part of this disabled rollout.
- Nginx OAuth query redaction, dedicated Google credentials, API approval, owner OAuth consent and real merchant validation belong to the later activation step. This release must not be reported as a connected Google integration.
