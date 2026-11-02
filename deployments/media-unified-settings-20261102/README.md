# Unified owner automation settings — release preparation

Local preparation only. No browser/server action, Git commit, provider request
or production data write has been performed by these tools' author.

Authenticated starting point: application `c78b50a11e02`, 427 runtime files,
container `0e33ad4fcfb9`, image `f456f7aaca24`, schema `h43fe567f803` / 165 tables,
frontend `569fa342f1c3`. The published prior controller is `8727edc4ae5e` and the
published worker helper is `c5acd2d20de6`; the prior unreleased recovery patch is
not used as deployment evidence. Existing monthly auto-prep remains **true**;
Google scheduling/cutoff, Meta execution/scheduling, environment order,
credentials, private boundary and existing permissions must remain unchanged.

The root agent captured the read-only [baseline](baseline.json), hash
`0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83`.
Live row hashes in that baseline are historical evidence. They are deliberately
not treated as a frozen live business database during development or prepare.

`release.py` uses a fresh `media-unified-settings-<source>-20261102` namespace.
The exact final application commit, reviewed build and baseline must be frozen
before packaging. The runtime overlay permits eight backend paths only. The
full source delta and protected application inventory are verified locally;
the source/payload/manifest pins are rejected while placeholders remain.

Prepare makes a WAL-aware SQLite clone, disables all workers in that isolated
container, provides no credentials or network, applies only
`h43fe567f803` → `i54af678a914`, and proves all 165 original tables/rows/sequences
preserved plus exactly four empty tables and five named indexes. No business
defaults or settings are seeded. Real server Python 3.10 route/owner canaries
run only in this isolated candidate.

Activation's exact-data boundary is explicit:

1. Authenticate the original runtime, full 427-file source, ordered environment,
   credential/private metadata, schema, CSP, active Nginx and current static
   inventory. Check that the known old container is the only RW database mount.
2. Create a stopped candidate and durable create/stop intent records. Stop the
   old writer. Reuse the exact published canonical mount and DB/WAL/SHM FD
   census, allowing legitimate RO private readers while rejecting unknown
   writers. Take two identical quiescent snapshots of every current 165 table
   and sequence; persist/fsync their proof privately.
3. Run the single transaction on the original database inode with network and
   credentials absent. Compare every original row and sequence exactly, and
   require four empty additive tables. Record `prestart-preservation.json`.
4. Start the candidate with every existing worker flag unchanged. From this
   point, existing workers may legitimately update business rows, including
   the two current policies' `last_checked_at`. Post-start checks therefore
   enforce all 169 table definitions, four empty new tables, source/runtime,
   writer identity, environment, credentials, private boundary, Nginx and CSP;
   they do not freeze active business rows.
5. Switch only the static root, preserving old hashed assets. No AI generation,
   settings apply, financial operation or public post is requested by release.

Recovery contains the known candidate, waits for the known migration to settle,
verifies only known schema shapes and authenticated old image/config/source,
and checks unknown writers before and after resuming the old application. It
retains any additive tables and all current business rows. There is no database
restore, downgrade, production DELETE, table drop or old-worker flag change.

The legacy helper graph is instantiated once per process. The worker helper is
never constructed, and the old mutable `pf.sample()` is never called after a
new public-root adapter is installed.

Focused tests: use the project Python with
`-m unittest discover -s deployments/media-unified-settings-20261102 -p 'test_*.py' -v`.
These cover the real WAL migration/rollback, every protected old table,
post-start heartbeat acceptance, schema rejection, RO/private reader handling,
unknown writers, and recovery before baseline or after candidate start.
