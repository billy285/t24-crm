# Media operations UI refinement — static release preparation

This namespace reuses the successful navigation release's static-only guard and
recovery behavior. Baseline application/frontend are `68fa858` / `6f71217e47f1`;
the independently preserved backend source remains `54e027a`, runtime `6f826ade`,
432 files and schema `i54af678a914` / 169 tables.

The allowed delta is explicitly limited to the confirmed Layout/navigation and
media-workspace presentation files plus focused tests: 11 paths, including six
reviewed new frontend/test files. Other additions, removals or source changes
are rejected. Application `835be7a06d614e11080274426d8110797f53b5ef` and reviewed
frontend `40f5a63a9156` are now frozen and packaged as 140 static members. No API,
backend, finance, permissions or private-space source is permitted to change.

Capture reads only immutable runtime/source/environment, schema definitions,
DB inode/pragmas, credential/private metadata, existing static files, Nginx and
CSP. It does not read or freeze business rows. The published previous static
helper is loaded once; no legacy mutable sample is called. Prepare only stages
static files and retains old hashed assets. Activate substitutes one Nginx root
atomically, reloads, then checks the immutable boundaries and live public
version/CSP. No backend/worker restart, DB write/migration, environment change,
provider action or publication is performed.

Recovery accepts only known old/new bytes, cleans only their known-prefix
temporary file, always reloads the authenticated old config even after a prior
reload failure, and checks old frontend/CSP before success. It never restores
the database or overwrites an unknown config. Generation-time command manifests
retain `executed:false`; reviewed server receipts establish actual completion.

The local release suite passes 97 tests plus six subtests, reusing prior focused
failure coverage. The author performs local preparation only; root handles
cloud execution, final QA and Git commits.
