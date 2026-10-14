# Sales lead enrichment release

Source: `5c71dd9baa8121acf53dbde760ff8791ee85eb90` from deployed baseline `33daaa5e36653dcc7d483e8197e76321f2328254`. Frontend: `218144e14118` → `69dec0425660`.

The payload permits exactly nine backend and nine frontend production files, plus committed tests in the source diff. It adds the sales quick-edit sheet, saved contact numbers, revision/conflict handling, sales-only profile history, and atomic profile/outcome submission. Company finance calculations, closing rules, commission logic, customer invitation permissions, and private workspace code are outside the allowlist.

## Migration and preservation

The reviewed migration is `d5b9a3e7f815` → `e6c0b4f8a916`:

- Three new tables: `sales_lead_enrichments`, `sales_lead_enrichment_audits`, and `sales_dial_attempts`.
- Three nullable columns: tasks `dial_phone`; call activities `dial_phone` and `dial_attempt_id`.
- Six explicit indexes, including unique activity `dial_attempt_id`, plus the audit `(lead_id, revision)` unique constraint.

Preparation executes the actual migration and candidate startup against an offline business database copy with network disabled. Verification checks exact new column definitions and indexes, unchanged original column/index definitions, hashes of every original row, empty new tables, and NULL new fields. The production migration repeats these checks after the original CRM is stopped and its stopped identity is independently inspected. Existing active and pending invitations, all five invitation provenance fields, private notes, material visibility, and role settings are compared separately. No existing invitation is activated or revoked.

## Operation

1. Build Vite from the pinned source; run `build_payload.py --source 5c71dd9baa8121acf53dbde760ff8791ee85eb90 --out <new-directory>` before the release-carrier commit. Source bytes and frontend build hash must match.
2. Transfer only immutable reviewed carrier files; verify all sizes and SHA-256 values. Server release directory must be root-owned, mode 0700, directly under `/opt/t24-crm/releases`.
3. Run `release.py --phase prepare` with the release directory, manifest/payload hashes, and independently verified private-service preflight file/hash. This requires the pinned old image, container, nginx configuration, and retained private helper.
4. Independently review the prepared receipt and pass its SHA-256 to `--phase activate --review-sha256 <hash>` with the same other arguments.
5. Verify the final deployed receipt, public version/readiness, and authenticated sales workflow separately.

Private API and worker are never restarted. Database backups are retained for inspection and are never restored by this tool. Before migration commits, recovery may restart the exact retained original CRM. After `e6c0b4f8a916` commits, recovery can only start the reviewed new image: the older application requires the old exact schema head. A failed forward recovery never falls back to the old image. Interrupted migration containers are settled before the committed schema is inspected. The old container must have a safe restart policy so it stays stopped across a Docker/host restart.

`--phase recover` requires the same reviewed preparation and activation identity. It is intended for interrupted activation; it rejects a release already marked successfully deployed. Static recovery validates temporary-file ownership, inode, permissions, and approved content before cleanup.

## Local release verification

`python -m pytest -q deployments/sales-enrichment-20261014/test_release.py` — **79 passed**.

Tests use the real migration on synthetic SQLite databases. They cover preservation of finance/commission/sales/invitation rows, all required indexes and unique constraints, migration-only empty/NULL checks, post-release data-safe recovery, exact manifest/source pins, stop verification before backup, restart policies, nginx recovery, and forward-only recovery failures. Real subprocess, Docker, and public operations are blocked in the test fixture. Passing these tests confirms the release tooling; it does not itself mean production is deployed.
