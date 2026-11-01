# Media workspace scale release

This is a non-migrating overlay of the two existing read-only projection
modules and a full reviewed frontend build. It does not change provider writes,
permissions, finance, closing, commission attribution, private-space code,
credentials, scheduling cutoffs, or dependency inputs.

The current source is the R3 backend `8b429dad8a2f` and mobile static
`adb948da237f`, frontend `c814db9f574f`, schema `g32ed456e792`. The new preflight
checks the completed static release and backend receipts, all 419 runtime files,
all 162 current tables, full environment digests, credential metadata, private
boundary, public inventory, effective Nginx and CSP. It captures two stable
samples including the two completed owner discovery reads. No business rows,
credential contents or provider requests are needed.

The authenticated root capture completed successfully. The canonical full proof
is `/opt/t24-crm/releases/media-workspace-scale-preflight-f65f71cb6e3e.json`,
SHA256 `f65f71cb6e3e617471dacddaddfd6323357279fc60fc382b5d35a71251356cc1`.
Only aggregate metadata is copied into local `preflight.json`.

After application review, focused tests, build and desktop/mobile QA, commit the
application and run `freeze.py --source-sha <full SHA> --preflight-summary
<absolute preflight.json>`. It requires the exact committed application delta,
every unchanged source file, and the matching local static build before writing
a fresh freeze and filling release pins. Then run `build_payload.py` with the
exact explicit source/frontend/freeze/summary arguments. Neither helper deploys.

Commit and push the immutable carrier containing the scoped tools, freeze and
artifacts. `make_commands.py` emits a prepare command only. Preparation builds
from the exact existing render-capable image without a network or dependency
installation. The isolated database copy runs with no credentials, no network,
and every worker disabled. It verifies the exact two GET routes, actual Python
3.10 parser, denied sales/finance before database access, original routes and
provider-disabled guards, then proves all copied rows/schema/metadata unchanged.

The root agent reviews the canonical server `prepared.json` before generating
activate/recover commands. Candidate identity is fsynced before the original
container is stopped. Each boundary checks every source file, all 162 table
hashes/schema, environment, credentials, privacy, original static inventory and
reviewed new static inventory. Nginx changes only the one static root; callback,
media privacy blocks and CSP remain exact. Recovery contains the durable known
candidate and resumes the original compatible runtime without restoring a
database or deleting production containers. Any independent business change is
preserved; drift stops the release for review.

Run synthetic tests with the existing backend venv:

```text
<backend-venv>/bin/python -m pytest -q deployments/media-workspace-scale-20261102
```

These files authorize no real post, comment reply, review approval, schedule,
task assignment, client binding or permission mutation. Actual publication still
requires the user's separate content confirmation.
