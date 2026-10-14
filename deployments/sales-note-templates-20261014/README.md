# Fixed sales note templates static release

Only `app/frontend/src/components/SalesCallRecord.tsx`,
`app/frontend/src/pages/sales-calling-controls.css`, and focused frontend tests
may change. The approved scope is eight fixed note templates; no configurable
template manager, new backend endpoint, AI request or database schema is added.

Baseline carrier is `81dc9f217eef33d2e7cb2a26bdff5de56e5fa883`, deployed source
`69c30a24b8ed37bd36f26eec474023b346a1c6c9`, frontend `cee9572db629`. The latest
CRM/private runtimes, nginx hash and old static root are pinned from the prior
verified release receipt and must pass fresh authenticated checks.

Use the existing guarded sequence: run scoped UI tests and build, commit only the
component/style/test source, freeze with `build_payload.py --source <full-sha>
--out deployments/sales-note-templates-20261014/artifacts`, run the local release
tests, review and commit helper/artifacts as a separate carrier, then generate
preparation commands using `make_commands.py --carrier <full-sha>
--preflight <reviewed-private-pins.json> --preflight-sha256 <sha256>
--out outputs/sales-note-templates-20261014`.

Preparation stages an immutable static root while retaining prior hashed assets
for existing tabs. Save and independently review exact server `prepared.json`
bytes, then add `--prepared-receipt <local-exact-receipt.json>` to generate pinned
activation and interruption recovery commands. Activation only compare-and-replaces
the nginx static root, tests/reloads nginx, and checks public assets and unchanged
runtime/database boundaries. Failure restores only the previous static root.

Compact receipts first validate complete schema-object hashes, then retain those
hashes/object counts, both database file identities, and every table's column hash.
The release never builds/restarts containers, mutates environment/permissions,
migrates or writes databases, or restores business records. Normal concurrent
business row activity remains allowed while runtime, file identity and schema
changes block activation. Verify template interaction/draft safeguards on isolated
fixtures and read-only live views after publication; no production test record is needed.
