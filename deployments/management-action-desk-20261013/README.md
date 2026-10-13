# Management action desk — static release

This release changes only the ManagementDecisions page and its scoped UI.
Financial calculations, closing conditions, backend services and private-space
source stay unchanged. The helper deploys only after reviewed immutable source,
artifact and authenticated preflight hashes are supplied.

## Accepted predecessor

- Product source: `a4ef1fbcf7d68b5a71e6afc01d4d89c16b68a61b`
- Frontend version: `175ea342c9eb`
- Release: `/opt/t24-crm/releases/finance-closing-compact-a4ef1fbcf7d6-20261013`
- Static receipt: `21d739861d5c20747e45d326ed11be043d29c473fe632f47d632ed6a1fad80e8`
- Previous helper: `d9e3f2e89f33d9516fe9dc3827407b11538a05f70d8612c963eedb8d1ab0f152`

A fresh authenticated preflight must still prove this root, receipt, helper,
runtime identities, environment and database identity/schema. Expected stage:
`MANAGEMENT_ACTION_DESK_AUTHENTICATED_READONLY_PREFLIGHT`.

## Source boundary

Exactly these application files may differ from the predecessor:

1. `app/frontend/src/pages/ManagementDecisions.tsx`
2. `app/frontend/src/components/ManagementActionDesk.tsx`
3. `app/frontend/src/pages/management-action-desk.css`

The latter two files must be new. All other tracked frontend and backend files
must remain byte-identical. Packaging verifies the frozen source commit, the
complete tracked frontend tree, no source symlinks or untracked source files,
and the exact build version. The deployed manifest additionally pins Finance,
closing-checklist and donut source hashes from the preceding release.

## Independent source proof

`format_version: 1`, `stage: MANAGEMENT_ACTION_DESK_PRESENTATION_SOURCE_PROOF`,
`source_mode: committed`, `baseline_source_sha` equal to the accepted product
source and `source_sha` equal to the new frozen product commit are required.
The reviewer independently supplies the proof file SHA-256.

Required hashes:

- `management_file_before_sha256` and `management_file_after_sha256`
- `component_file_sha256` and `styles_file_sha256`

Required true flags: `financial_calculations_unchanged`,
`close_conditions_unchanged`, `private_workspace_source_unchanged`,
`data_reads_unchanged`, `mutation_handlers_unchanged`, and
`management_presentation_only`.

Required `evidence` fields:

- `preserved_api_calls_sha256`, `preserved_finance_region_sha256`, and
  `protected_application_inventory_sha256`: SHA-256 hashes.
- `preserved_api_call_count` and `protected_application_file_count`: positive
  integer counts.
- `preserved_functions`: nonempty mapping of function names to
  `before_ast_sha256`, equal `after_ast_sha256`, and nonempty `normalization`.

These are bindings to the independent source review. UI interactions and live
acceptance are separate checks. `build_payload.py --help` documents packaging.
Package from the product commit before creating an artifact-carrier commit.

## Publication boundary

`static_release.py` has separate `prepare` and `activate` phases. Activation
requires an independently observed prepared receipt hash. It retains previous
hashed assets, holds the existing release lock and compare-and-swap replaces
only the checked Nginx static root, then validates and reloads Nginx. Public
assets, authentication, runtime and schema boundaries are checked again.

Failure recovery restores only the static root. It never restores or mutates
databases, credentials, environment or application services. Concurrent Nginx
changes are rejected rather than overwritten. Legitimate live application data
changes do not cause a stale financial-record restore.

Release directory: `management-action-desk-<product SHA first 12>-20261013`.
Only the explicit `-retry2` alternative is accepted.

The focused tests use synthetic source, runtime and schema objects and do not
contact the server, providers or any live financial records.

## Prepared product candidate

- Product source: `622055f8e054f3a08dcb555f53707b9665d24627`
- Frontend version: `2b5eb3d9a00f`
- Independent proof SHA-256: `afc1fbdcfac0021291843ccd661345d02dca4ee85a10b9695b5f0f0251b55801`
- Reviewed source proof: `source-proof.json`; verifier: `verify-source.mjs`.

This records packaging inputs, not a publication claim. The root task owns
artifact-carrier commit/push, authenticated prepare/review/activate, and live UI
acceptance. These steps remain separate from synthetic release-tool tests.
