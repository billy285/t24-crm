# Media operator queue and per-merchant monthly workflow

This non-migrating release builds on the completed review-month release
`196781fbf68c`, frontend `18d102381fef`, runtime `bf4b4fd11022`, schema
`g32ed456e792`, and 162 populated tables. The captured baseline is
`8407a1e8596fb15b9937ae168cbbad5374e54bd653522a23d9360e2eeec3a508`.

The application scope is the media work queue, continuation context, merchant
preparation checks, and existing owner-reviewed Google monthly flow. Backend
changes are restricted to seven existing modules: the two monthly input schemas,
the two monthly routers, and the monthly, monthly-workflow, and workspace services.
There are no migrations, new runtime files, dependency changes, financial or
commission computations, closing conditions, customer grants, or private-space
changes. The same existing two GET-only workspace routes serve the richer queue. A single
non-public owner-only archive endpoint retains unused draft batches and recovers
the original request, so stale input can be replaced without duplicate content.
Monthly mutations remain owner-only and use the native version, request replay,
image, customer, binding, content, and separate publication-confirmation checks.

`preflight.py` loads the exact completed review-month helper and canonical
prepared/deployed receipts using its supported stopped-parent recovery loader.
It samples the live source, environment, credentials metadata, private boundary,
static tree, Nginx/CSP, schema and all 162 row hashes twice. Only a new root600
aggregate proof is written; no credential or private content is exported.
`make_capture.py` embeds and pins those reviewed bytes. The parent executed that
read-only capture successfully; `preflight.json` is the bounded returned summary.

`freeze.py` requires an explicit new committed application tree, exact reviewed
application delta, and current reviewed static build. The application and final
frontend pins are deliberately unusable until that freeze. `build_payload.py`
packages only the seven existing backend files and the reviewed static tree.
`make_commands.py` requires the pushed immutable carrier and emits prepare first.
Activate/recover commands require the canonical server prepared receipt and are
not emitted from a guessed or transport-only hash. No generator executes a phase.

Preparation builds from the exact current render-capable image without network,
installation, or migrations. A separate database copy runs with no credentials,
no network and every background worker disabled. Native route and nonowner
checks run along with actual Python 3.10 timestamp, exact review-month basis,
generic merchant-month rules, legacy November slots, DST rejection and owner
boundary canaries, including all16 exact monthly routes and the archive owner
boundary. Every copied row, schema and metadata must remain unchanged.

The exact completed-parent lineage matters: the native public build capture is
resolved through the prior review-month flow to the Main preflight's pinned
onboarding module; the native existing-route probe is resolved through that
same Main to its onboarding flow. This avoids silently depending on a helper
method that is not present at the newly added wrapper layer.

Activation records the durable candidate identity before stopping the current
container, clones its exact environment and protected mounts, and rechecks all
source, rows/schema, worker cutoffs, credentials, private boundary and static
inventories at each boundary. Nginx changes only one static-root string; CSP and
all privacy locations remain exact. Recovery stops the known candidate and
resumes the exact compatible original without restoring any database, removing
production containers, or executing code inside a stopped historical parent.

Real posts, replies, and public schedules are never submitted by this release.
The parent must independently review the prepared receipt, activate, and verify
the production desktop/mobile story before claiming deployment complete.

## Deployed result

Application `e0f39295a912ac6f7518d523a860ee9ca649d54e`, frontend
`04e77e374e74`, was prepared and deployed through authenticated Alibaba Cloud.
Canonical prepared receipt: `55586cffdbea74f52330cb68bbda90c1871d9ffc80013e44e7e0c953962a6945`.
Canonical deployed receipt: `e1af41bb8fe55fee6ca3df26b18a9a7c28a8595946781ac381380907cc2d6638`.
The parent verified all 43 authorized production customer rows over four pages,
exact merchant search, persisted 12-item November review, fresh next-merchant
navigation and return to the queue. Desktop 1280px and mobile 390/320px had no
horizontal overflow. Staff isolation was validated in synthetic UI and backend
fixtures, not a new live employee session. No real review, schedule, post, reply,
permission or business-record mutation was submitted during UI acceptance.
Production screenshots remain user-local; only sanitized assertions are retained.
Backend protected regression: 1,386 passed. Frontend: 252 passed. Release tools:
125 passed. Scoped ESLint and Vite build passed. Full TSC retains only the
existing unchanged `Finance.tsx:5778` TS2322 baseline error.
