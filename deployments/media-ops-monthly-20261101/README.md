# Northern Pasta monthly draft preparation release

This additive release preserves the current 150 populated tables, changing only the explicitly reviewed Alembic head from `cefa9b12a358` to `df0ba123b469`, and creates three empty tables: `media_monthly_profiles`, `media_monthly_runs`, and `media_monthly_items`. It does not alter provider credentials, scopes, company finance logic, closing conditions, commissions, customer permissions or private workspace.

Generation and adoption prepare drafts only. No Google/Meta action, schedule, image-delivery lease, task approval or public publication is executed by these release tools. Existing full environment values and their order remain exact: Meta execution/scheduling stay off, Google scheduling retains its existing activation cutoff, and every credential/private boundary is preserved.

The frozen `capture-command.sh` loads the exact deployed merchant-view helper and receipts for source `5a904dd925f03296c07018f83e97277f5f90dd08`, frontend `42de3d4757db`, runtime `199e8a448aa3e93a5347f1e93cb3e98600c8433fa18098f7b546a3d63f6eaa03`, and image `af0ba571d5b5a2dc46187c7083be17162803b4d98f8d45347c5da2b0f4378479`. Two stable samples must match across all 150 table hashes and every runtime, source, environment, schema, credential-metadata, private, static and Nginx/CSP boundary. Its only write is the root-private aggregate proof. Finish any legitimate audit/cache reads before capturing; later drift is rejected rather than ignored.

Application source is frozen at `6ab1ded2e139e8622596a2a71ca1041015a0b95f`, frontend `628bd059a499`, application freeze `2196fcdb66246691141206b121099e7e0a8f67f91099cec1264b7feea1aa8547`, current protected proof `d2129acab27861e9b6270a47aee2b9258f9b77f1d9a72db1cee477f962ebe9a5`. Exact source delta: 15 files (six backend runtime, five frontend runtime, four tests). The actual migration defines the pinned three table shapes and two indexes; 126 synthetic release/transport/migration checks pass. The deterministic package has 146 members. Immutable-carrier staging and the separately reviewed canonical server preparation receipt remain mandatory; no live phase has executed.

Preparation uses the exact existing image with only five reviewed new backend modules and the exact root-owned existing merchant-projection adapter and full deterministic static tree. No dependencies are installed. The complete database is cloned into an isolated, network-free container without credentials or workers; the exact migration runs transactionally, all old rows/table/index definitions stay exact except the reviewed schema-head value, and the three new tables stay empty. Startup and canaries must preserve the resulting data and metadata. Python 3.10, exact route registration, owner-only denial before SQL/AI access, and existing capability guards are verified.

Switching requires the separately reviewed canonical server `prepared.json` hash. The candidate ID and exact production pre-migration snapshot identity are durably journaled before migration. The original worker is stopped before the migration begins. Complete old/new source and static inventories are checked at each boundary; only the single Nginx static-root value changes.

Recovery settles the durably identified migration first. Before a migration commit, it may resume the exact original runtime against the old schema. After the new head commits, recovery is forward-only with the known candidate and preserves independent rows in both original and new tables. It never restores the database, runs downgrade, drops tables or deletes production containers. A completed deployment requires a separate recovery review.

After real use, the new monthly tables will contain legitimate profiles, runs and draft links. Any future release must capture all 153 populated tables and the active new head; it must never reuse the initial empty-three-table assumption as a general baseline.

Run local synthetic release and transport checks:

```text
python -m pytest -q deployments/media-ops-monthly-20261101
```

Only the root agent executes reviewed commands against the authenticated target. Exact public post text, image and schedule remain subject to the owner's later confirmation.
