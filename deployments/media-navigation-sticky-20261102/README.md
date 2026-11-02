# Media navigation — static-only release preparation

This release changes the navigation presentation only. The allowed application
delta is `app/frontend/src/components/media-merchant-workspace.css`; additional
fixture tests require an explicit scope update before freeze. No backend source,
container lifecycle, database migration/write, environment value, worker flag,
permission, credential or private-space behavior is changed.

The read-only capture authenticates the completed unified-settings deployment:
source `54e027aad00e81a4ebb747ada1299e7a10e1ec52`, frontend `32a580644502`,
432 backend files, schema `i54af678a914` / 169 tables, container `6f826ade371a`
and image `1b6caabf90c8`. It verifies exact runtime/config, ordered environment,
private and credential boundaries, table definitions, immutable DB pragmas,
database inode, existing public files, Nginx and CSP. Two immutable samples
must agree. It does not read business rows or freeze row/sequence values; normal
existing policy heartbeats and financial background activity remain live.

The published unified-settings helper is loaded once by hash. No old mutable
`pf.sample()` or worker-helper constructor is used. The new static controller
directly checks its captured immutable boundaries after configuring the new
public-root adapter.

The captured baseline is `6c8dcf5954a5ccac79b323dc40a67e001034e232d27505a55d101c451a103216`.
Application `68fa8589101f4a3075141c910ec51fd86b9ec9ed` and reviewed frontend
`6f71217e47f1` are now frozen. `freeze.py` pins the exact single-CSS application
delta and reviewed static inventory. `build_payload.py`
creates a deterministic tar containing `static/` files only and records the
protected inventory of all other application files. `make_commands.py` emits
commands tied to an immutable carrier commit; it never executes them.

Prepare stages static files and retains every old hashed asset without changing
the active site. Activate atomically substitutes the single Nginx static root,
reloads Nginx, and checks runtime/source/environment/schema/private boundaries
again plus the loopback public version and CSP. No backend or worker is restarted.
On a failed public check, recovery restores only the exact original static root;
it does not overwrite an unknown Nginx change or restore any database.

Capture and command-generator `executed:false` fields describe generation time.
Actual server prepared/deployed receipts must be separately reviewed before
claiming a release. All cloud execution and owner UI acceptance belong to the
root agent; this tool author performs local preparation only.

The focused suite passed 97 tests plus six subtests. Independent read-only
review confirmed the root-adapter and recovery boundaries. Recovery always
reloads the known old config, including when a prior reload failed after the
disk root was restored, and verifies the old frontend plus CSP on the live
loopback listener before recording success. Only known old/new-prefix Nginx
temporary bytes may be cleaned; unknown content is retained and rejected.

Focused local checks:

`python -m pytest deployments/media-navigation-sticky-20261102 -q`
