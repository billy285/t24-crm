# Unified owner automation settings — deployed and verified

The root agent deployed application `54e027aad00e81a4ebb747ada1299e7a10e1ec52`
using carrier `89a83ab0e0a595b29c56d7e6d4fa04553d4969f5`, then completed
read-only postflight at `2026-11-02T07:44:41.185996+00:00`.
Frontend `32a580644502` and 432 backend files run in authenticated container
`6f826ade371a37fbf405c2e90ee405abb4e7d5ad5c9344139cb65a46596e5757`, image
`sha256:1b6caabf90c809def8e180811336ebdc12e49305ad0f11bf4126730790d09bee`.
The schema is `i54af678a914` / 169 tables.

The four new settings tables remain empty: no merchant configuration was seeded
or applied. Existing ordered environment values and worker flags remain unchanged:
monthly auto-prep **true**, Google scheduler **true**, Meta execution/scheduler
**false**. Finance calculations, closing conditions, commission ownership,
existing permissions and the private-space boundary were preserved. The release
and its postflight requested no provider call, AI generation or public post.
Real publication still requires the owner's confirmation.

The release-tool author performed local preparation and audit only. The root
agent performed the cloud actions and live UI acceptance. Generation-time
`executed:false` command manifests retain their original meaning and bytes;
the following receipts establish the actual executed result.

## Final evidence

- [Final release status](final-release-status.json) contains aggregate pins and
  boundary evidence only; no merchant names, captions or private images.
- [Independent prepared review](prepared-review.json) validates the manifest,
  payload, isolated migration and canonical prepared receipt
  `c96bb2707cfd7c1c83a0bc01e7e17671a5997b20f09d27b44bbb42801ab91482`.
- [Deployed transport receipt](deployed-envelope.json) has canonical receipt hash
  `b5d270391535704c36a756a8d1a3b8f0cf0c1e7e312ceb64ba64fd842b09d68d`.
- [Read-only postflight](postflight.json) has canonical/file hash
  `cd5748bcaece14f756b6d4db64e4fd44b36aecfe5e430b88996b3318fa2bd1a3`.
  All 12 selected media tables retain their pre-start row and shape hashes.
  Only the existing policies table changed after start: both enabled policies
  showed normal heartbeats 18.5 seconds before sampling. No selected media table
  requires review; no new occurrence or publication was created by release.
- Root live UI acceptance verified settings/template/platform reads and a
  390px mobile document with 390px scroll width and no horizontal overflow.
  Private UI evidence stays outside these public audit artifacts.

Canonical receipt hashes use sorted JSON, indent 2 and trailing LF. Exclude the
`receipt_sha256` transport field when recomputing a server receipt. Verification
is tied to its sample time; active business rows remain live afterward.

## Frozen artifacts and prior baseline

The root captured [baseline](baseline.json) hash
`0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83`.
It authenticated source `c78b50a11e02`, 427 runtime files, container
`0e33ad4fcfb9`, image `f456f7aaca24`, schema `h43fe567f803` / 165 tables and
frontend `569fa342f1c3`. Its historical row hashes were not frozen across normal
production activity. Published prior controller `8727edc4ae5e` and worker helper
`c5acd2d20de6` remain the historical references; the older unreleased recovery
patch was not treated as deployed evidence.

The application delta contains 17 paths; the runtime overlay permits eight
backend paths only. Frozen helper/artifact hashes are:

- Release helper: `b9d954130b99802bf444fe1ce99b73ba869c21ca95d1387ebb6d124d06ea109e`.
- Manifest: `0292d5bf251f16b03bfb0692942715c0cd304f998fe644211b95e780433341e3`.
- Payload: `64537d65fbdf9b8f249d004f6639e9d2d7b5c28ac14bf43f256cee3cdf442439`.

These bytes and their pins were not changed for final audit. The fresh server
namespace is `/opt/t24-crm/releases/media-unified-settings-54e027aad00e-20261102`.
The legacy graph is instantiated once per process; the old worker helper is
never constructed and mutable `pf.sample()` is not called after installing a
new public-root adapter.

## Exact data-preservation boundary

Prepare made a WAL-aware SQLite clone with no credentials or network and all
isolated workers off. It applied only `h43fe567f803` → `i54af678a914`, proving
all original 165 table definitions, rows and sequences preserved, with exactly
four empty additive tables and five named indexes. Server Python 3.10 owner
route canaries ran only in that isolated candidate.

Activation authenticated the original runtime/source, ordered environment,
credential/private metadata, schema, CSP, Nginx and static inventory. It created
a stopped candidate, persisted create/stop intents, then stopped the known old
writer. Canonical mount and DB/WAL/SHM FD checks allowed legitimate read-only
private readers and rejected unknown writers without stopping them. Two equal
quiescent snapshots established the current all-165-table baseline.

The transaction migrated the original database inode and compared every old
row and sequence before candidate start. Quiescent proof:
`1743b67147090a464b8529fd8a0b011cc4a0a65c8126103567bb1079aceca3f3`.
Pre-start preservation proof:
`3ae22282dc1a0a10fd1d9c6ffd140629b70c9d13dc978f9165a98139cabf1498`.
Writer checks ran again immediately before candidate start and in the live
boundary check.

After candidate start, normal existing worker updates were allowed. Validation
continued to enforce all 169 definitions, four empty new tables, exact runtime,
source, environment, credentials, private boundary, writer identity, Nginx and
CSP. It did not freeze active business rows or introduce table exceptions to
the pre-start all-row comparison. Only the static root switched; old hashed
assets were retained.

## Validation and recovery

The release/failure suite passed 31 tests and the separate read-only postflight
suite passed three tests. These cover real WAL migration/transaction rollback,
every old table, pre-start rejection and post-start acceptance of normal policy
heartbeats, schema rejection, unknown writers, read-only private readers and
recovery gaps. To run the local checks with the project Python:

`-m unittest discover -s deployments/media-unified-settings-20261102 -p 'test_*.py' -v`

Recovery contains the known candidate, settles the known migration and verifies
known schema shapes plus authenticated old image/config/source/environment.
Writer census gates resuming the old application. Recovery retains additive
tables and all current rows; no database restore, downgrade, table drop,
production DELETE or worker-flag change is used. Recovery was neither needed
nor requested in the successful deployment.
