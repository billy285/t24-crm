# Sales quality-select height static hotfix

Only `app/frontend/src/pages/sales-calling-controls.css` and focused frontend
tests may change. The patch gives the native quality-filter select enough content
height after border/padding for its current text line. No route, request, outcome,
draft, data, permission, finance or private-space code changes.

Baseline carrier is `a4bed09cebb68c0f4f5a51d013512bc91bdc5de8`, deployed source
`969165eaec8a6bd3772dbd44e556b88d8d192230`, frontend `783a9f6bb897`. Live
CRM/private runtime, nginx and old static-root pins remain required.

Use the same guarded sequence: commit the scoped source, build the frontend,
freeze with `build_payload.py --source <full-sha> --out
deployments/sales-controls-height-20261014/artifacts`, run the local release tests,
review and commit helper/artifacts as a carrier, then generate preparation commands
with `make_commands.py --carrier <full-sha> --preflight <reviewed-private-pins.json>
--preflight-sha256 <sha256> --out outputs/sales-controls-height-20261014`.

Preparation only stages static resources. Review the exact server `prepared.json`
bytes, then add `--prepared-receipt <local-exact-receipt.json>` to generate pinned
activation/recovery. Activation only compare-and-replaces the nginx static root,
tests/reloads nginx, and validates public assets plus unchanged runtime boundaries.
Failure restores only the prior static root. No container or database write occurs.

Receipts validate each complete schema-object dictionary against its actual digest,
then retain only that digest, object count, database file identity and every table's
column hash. This preserves schema drift detection while avoiding large SQL text
in console output. Ordinary record activity remains allowed and is never rolled back.
