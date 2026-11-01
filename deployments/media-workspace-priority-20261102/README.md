# Media workspace exception-priority static refinement

This followup orders the owner's exception preview before taking its first six
rows: failed/unknown high-severity issues first, then review/overdue actions,
then routine setup issues and a stable merchant ID. The application source
change is restricted to `MediaPortfolioPanels.tsx` and its focused UI test.

Current backend remains the deployed Media Workspace Scale source
`7697e1adc61f72cf6b13896a3a41389d8a31b09d`, frontend `6a8a9ac27c6c`,
419 runtime source files and 162 tables. It does not change finance, closing,
commissions, grants, private-space source, dependencies, provider capabilities,
workers, credentials or content. No public content is approved or published.

The authenticated fresh baseline is pinned in `preflight.json`; the complete
row/schema/environment/private/static proof remains on the server in its new
root600 evidence file. Loading the completed scale helper uses its explicit
recovery dependency path, which validates the stopped pre-scale container's
frozen source rather than executing it. The current live runtime and inventory
must still exactly match the completed scale deployment.

`freeze.py` accepts the explicit committed application source and matching local
build, verifies the exact two changed source files and every other application
file, then pins the static release and packager. `build_payload.py` packages only
reviewed static files. `make_commands.py` requires the exact pushed immutable
carrier and generates a prepare command; activate/recover commands require the
canonical server prepared receipt. These commands are generated, not executed,
by this directory's tools.

Preparation stages a new public static root while proving all current rows,
schema, environment, runtime, credentials, private boundaries, original static
bytes and CSP unchanged. Activation changes only that one public-root string
and reloads Nginx. It verifies public version and CSP, then compares all 162
current tables and exact runtime again. Recovery restores only the exact prior
Nginx root. No database restore, container restart, dependency installation,
provider request, account change or permission change is implemented.

Synthetic guard tests cover 88 cases: static payload/source/link/hash attacks,
all-table/source/runtime/environment/private/CSP boundaries, canonical receipt
and carrier changes, exact root substitution and failed-acceptance recovery.
The parent performs the actual authenticated publication and desktop/mobile QA.
