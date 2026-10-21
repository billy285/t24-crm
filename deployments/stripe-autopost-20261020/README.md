# Opt-in Stripe automatic receipt pilot

This release adds per-service automatic posting policies and durable work jobs.
The release itself creates two **empty** tables and enables **no** policy. Owner
trial validation and explicitly selected pilot activation are later application
operations, separately verified against the unchanged historical ledger.

Baseline application: `7caf0f652525e593c33d6bfea9724c72efd3aab8`, frontend
`0f8ad5c23245`, schema `e2b6c0f8a345`. These values are checked against a fresh,
authenticated server proof rather than inferred from a public health endpoint.
The new schema `f3c7d1a9b456` adds only `stripe_auto_posting_policies` and
`stripe_auto_posting_jobs`, plus their two lookup indexes. No seeds are shipped.

## Local preparation

1. Review `preflight.py`; generate `preflight-command.sh` with
   `make_preflight_command.py`. The generated command is read-only. It prints a
   hash and compressed JSON proof. Decode and verify the complete proof before
   saving it as `outputs/stripe-autopost-20261020/preflight.json`. A truncated
   browser output is not a valid proof. The compact receipt exports table counts,
   row hashes and shape hashes; complete table schemas/rows remain on the server.
2. Complete source review, focused regression tests, and a frontend build. Commit
   the reviewed application. `build_payload.py --source <application-sha>
   --preflight <proof.json> --out deployments/stripe-autopost-20261020/artifacts`
   requires the exact nine backend runtime files, eight frontend source files,
   and five focused tests (the two existing reconciliation browser specs change
   only their synchronized explanatory-text assertion). The additional existing route is
   `routers/management_decisions.py`: month closing takes the shared transaction
   lock before its business reads, preventing a concurrent new receipt from
   being missed by a closing snapshot. Financial calculations and closing
   eligibility conditions are unchanged. Every other tracked application file
   remains protected.
3. Review and commit tooling/artifacts as an immutable carrier. Generate commands
   with `make_commands.py --carrier <carrier-sha> --preflight-receipt <proof.json>
   --out outputs/stripe-autopost-20261020`. This does not contact the server.

## Server release

1. Execute the generated proof installer, then the immutable acquisition/prepare
   command. Preparation clones the current SQLite database into the protected
   release folder, verifies the backup, applies the exact migration inside an
   explicit transaction, and compares every original table row/schema/index and
   every original SQLite schema object. The only additions must be the two empty
   tables and their approved indexes.
2. The exact current local image is overlaid without package installation,
   pulling, or build networking. The candidate runs in actual Python 3.10 with
   no network, no mounted credential, and both Stripe workers disabled. Readiness,
   source hashes, empty policies/jobs and unchanged original rows are checked.
3. Independently review the actual prepared receipt. Only then regenerate the
   command package with `--prepared-receipt <actual-prepared.json>`, which produces
   activation and forward-recovery commands pinned to the reviewed receipt hash.
4. Activation stops the original CRM, verifies a restorable backup, applies the
   additive migration, and starts the exact reviewed image with the original
   environment, networks and mounts. The public static directory is new; all old
   assets remain retained. Nginx changes only its one public-root selection.
5. Readiness, application source inventory, frontend version, private runtime,
   original financial/permission rows and two empty new tables are rechecked.
   The owner may then perform the separately authorized 3–5-service trial and
   enable only passing selected policies. Historical pending invoices are not
   converted into automatic receipts by release tooling.

If any original row changed since the preflight, refresh and review the proof.
Never ignore the difference or restore a prior production database. After the
new schema exists, recovery uses the same reviewed new image; it never starts
the old application against that schema. Before migration, an aborted operation
may resume only the exact original runtime against its unchanged old schema.

All source acquisition and server execution remains the root agent's operation.
This folder's preparation scripts do not claim that deployment or a financial
pilot has been completed.
