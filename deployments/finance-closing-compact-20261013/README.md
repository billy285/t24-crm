# Compact finance closing checklist — static release

This release changes the presentation of one closing-checklist region only. The
existing checklist data, actions, finance calculations and close conditions are
preserved. These helpers do not deploy until invoked with independently reviewed
source, artifact and authenticated preflight hashes.

## Accepted predecessor

- Product source: `1d830fb37ac4812b8b7dcb6210e15b9bf3418e19`
- Frontend version: `fe34928582ac`
- Release: `/opt/t24-crm/releases/finance-donut-ranking-1d830fb37ac4-20261013`
- Static receipt: `eabe49362be8fdc8ce09513437e716d37f42773e5f21af45163a6fee0343dd66`
- Previous helper: `9af049bf965d7dcc4a3187bcde48dc7cade2fdcb2f82360f5613c28a22de6f23`

The current host, root, receipt, helper, application runtimes, environment and
database identity/schema must still match a fresh authenticated preflight. The
preflight stage is `FINANCE_CLOSING_COMPACT_AUTHENTICATED_READONLY_PREFLIGHT`.

## Source boundary

Exactly these app files may differ from the predecessor:

1. `app/frontend/src/pages/Finance.tsx`
2. `app/frontend/src/components/FinanceClosingChecklist.tsx`
3. `app/frontend/src/components/finance-closing-checklist.css`

The two component files must be new. Every other tracked frontend source file
and every backend file must remain byte-identical. The complete frontend tree,
including previously released donut components, must match the frozen commit;
untracked source files, symlinks and incorrect build versions are rejected.

## Independently reviewed source proof

The proof JSON uses `format_version: 1`,
`stage: FINANCE_CLOSING_COMPACT_PRESENTATION_SOURCE_PROOF`,
`source_mode: committed`, and `baseline_source_sha` equal to the predecessor.
`source_sha` identifies the exact new committed product source. Required hashes:

- `finance_file_before_sha256`
- `finance_file_after_sha256`
- `component_file_sha256`
- `styles_file_sha256`
- `preserved_finance_ast_sha256`
- `preserved_finance_bytes_sha256`

`closing_regions_replaced` must be the integer `1`. Required true flags:
`financial_calculations_unchanged`, `event_handlers_unchanged`,
`close_conditions_unchanged`, `table_cells_unchanged`, `dialogs_unchanged`,
`private_workspace_source_unchanged`, `data_reads_unchanged`, and
`component_presentation_only`.

The reviewer supplies the proof's SHA-256 to `build_payload.py`; the manifest
embeds that exact proof and hash. Package from the product commit before creating
any later artifact-carrier commit. `build_payload.py --help` documents arguments.

## Publication boundary

`static_release.py` uses separate `prepare` and `activate` phases. Activation
requires the independently observed prepared receipt hash. It holds the existing
release lock, verifies runtime/schema boundaries, retains previous hashed assets,
and changes only the checked Nginx static root. It validates and reloads Nginx,
checks public assets and authentication, and verifies boundaries again. On a
failure it restores only that static root, using compare-and-swap protection; it
never restores or mutates databases, credentials, environment or application
services. A concurrent Nginx change is not overwritten.

Public/release directory name:
`finance-closing-compact-<first 12 characters of product source>-20261013`
(only the explicit `-retry2` alternative is accepted).

Tests cover immutable source/proof scope, malformed or drifting inputs,
protected static payloads, predecessor lineage, schema/runtime boundaries,
retained assets, recovery and concurrent Nginx changes. They are synthetic and
do not contact the server or providers.
