# Media workspace review-month and exception-priority followup

This non-migrating followup combines the two verified acceptance refinements:
owner exceptions are ordered before the first-six preview, and monthly review
batches keep their actual nominal month while ordinary task rows use the same
Beijing-month basis as the workspace calendar. It changes four application
files against the currently deployed `7697e1adc61f`: one backend read-only
service, its focused test, one frontend component and its focused test.

The current live source inventory remains 419 files, frontend `6a8a9ac27c6c`,
schema `g32ed456e792`, and all 162 populated tables. The only backend overlay is
`services/media_workspace.py`; the router and every other runtime file remain
unchanged. No finance, closing, commission, customer/employee grant, private
workspace, dependency, credential, worker policy or provider write is included.

The exact prior priority preflight is reused byte-for-byte (`504d511d...`), with
its complete root600 proof `media-workspace-priority-preflight-cd201ac67a0b.json`.
Its completed Main helper is loaded with the explicitly supported recovery
dependency path, so the old stopped historical container is not executed. Normal
preparation and activation still require the exact running current Main image,
all 419 current sources, current environment and all 162 row/schema hashes.

`freeze.py` verifies the explicit committed application source, exact four-file
delta and current reviewed build. `build_payload.py` includes the one backend
service and static files only. `make_commands.py` requires the pushed immutable
carrier and generates prepare first; activate/recover require the canonical
server prepared receipt. No command generator executes a server phase.

Preparation builds from the exact existing render-capable image with no network
or dependency installation. An isolated copy of the current database runs with
no credentials, no network and all workers disabled. It checks original native
routes, denied roles before SQL, provider-disabled guards, actual Python 3.10,
and the exact November/UTC-boundary review-month regression before requiring
all copied rows, schema and metadata unchanged.

Activation records a durable known candidate before stopping the original,
clones the exact current runtime environment, and checks every source, all 162
tables, credentials, private boundary, static inventory, Nginx and CSP at each
boundary. Only the existing single static-root string changes in Nginx. Recovery
can load the exact stopped current original without Docker exec, contains the
known candidate, and resumes the compatible original without restoring any
database or deleting production containers. Real content publication remains
separately confirmed by the user.

111 synthetic tool checks pass, covering exact application/payload/carrier and
receipt pins, source/path/link attacks, every preservation boundary, pure runtime
canaries, durable rollback and nine fresh-process stopped-parent recovery cases.
The parent agent performs authenticated server phases and production UI QA.
