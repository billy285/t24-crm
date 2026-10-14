# Merchant-pool industry release

This package changes only the sales merchant pool. The source allowlist is:

- `app/backend/routers/merchant_pool.py`
- `app/backend/services/merchant_industries.py`
- `app/frontend/src/pages/MerchantPool.tsx`
- `app/frontend/src/pages/merchant-pool-industries.css`
- Focused tests under the existing backend/frontend test directories.

The five-column merchant import template, company financial formulas, close conditions,
commission attribution, customer invitation rules and private workspace remain protected.
There is no schema migration and no production row update in this release. Classifying
the 20 imported restaurant rows is a separate authorized UI operation after publication.

## Baseline to verify live before preparation

The last recorded release was carrier `9c4efa19a71a9db0f66619070759f57df2e1a6d7`,
deployed app source `5c71dd9baa8121acf53dbde760ff8791ee85eb90`, and frontend
version `69dec0425660`. Its CRM container/image, static root, nginx SHA and
schema head are pinned in `release.py`. These records are a guard, not proof that
the server is still at that state. Any live drift rejects preparation.

`release.py` hash-checks and reuses the already deployed sales release's filesystem,
Docker, SQLite snapshot, public-static and private-runtime guard primitives. It adds
only a no-migration prepare/activate/recover workflow. The legacy helper's identity
is checked at every use; no download, environment print or credential export occurs.

## Local preparation

1. Run backend/frontend focused tests, build frontend, and review the exact source delta.
2. Commit the four scoped app files and focused tests as the source commit. Do not mix
   changes from other features into that commit.
3. From the repository root, run:
   `python3 deployments/merchant-industry-20261014/build_payload.py --source <full-source-sha> --out deployments/merchant-industry-20261014/artifacts`
4. Run:
   `python3 -m unittest discover -s deployments/merchant-industry-20261014 -p 'test_*.py' -v`
5. Commit the deployment helper and frozen artifacts as a distinct carrier commit.
   Publish that carrier only after reviewing the manifest and source/build identities.
6. Generate preparation commands without executing them:
   `python3 deployments/merchant-industry-20261014/make_commands.py --carrier <full-carrier-sha> --preflight <reviewed-server-private-pins.json> --preflight-sha256 <sha256> --out outputs/merchant-industry-20261014`

## Server prepare and publication

Execute the generated `prepare-command.sh` through the authenticated server console
only after verifying the correct host and the live CRM/private boundaries. Preparation
acquires exact carrier files, builds the new image from the exact current local image,
starts the candidate and original image on an offline business DB copy with networking
disabled, compares full table schemas/indexes/rows, and stages a fresh immutable public
root while retaining old hashed static assets. Preparation leaves live CRM running.

Review the receipt independently. Save the exact bytes of server `prepared.json` locally
(not the displayed JSON with an added `receipt_sha256` field), then rerun `make_commands.py`
with `--prepared-receipt <local-prepared.json>` to pin activation and interruption recovery.
Execute the generated activation command once. It stops only CRM, takes a protected
snapshot, checks the unchanged existing schema, starts the reviewed image with the
original runtime configuration, compares all business rows before publication, then
atomically replaces the nginx static-root configuration and checks readiness/version.

Any activation failure restores the exact retained original CRM and static configuration
without restoring or writing the production database. `recover-command.sh` handles an
interrupted activation; it rejects unowned containers, unexpected nginx state or schema
drift. A completed successful release requires a separate reviewed rollback decision.

After publication, verify the live merchant list, industry/state filters, merchant details,
batch selection/assignment preview and access boundaries. Then classify the authorized
imported 20 records through the UI; do not modify ownership or assign sales unless asked.
