# Media navigation — deployed and accepted

The root agent deployed application `68fa8589101f4a3075141c910ec51fd86b9ec9ed`
with frontend `6f71217e47f1`, using carrier
`928f517be094541434594212ad4a5ca3d5044ed0`. The only application change is
`app/frontend/src/components/media-merchant-workspace.css`.

This was a static-only release: static files were staged, old hashed assets were
retained, and the single active Nginx public root was atomically switched and
reloaded. The backend and workers were not restarted. Backend source
`54e027aad00e81a4ebb747ada1299e7a10e1ec52`, all 432 backend files, schema
`i54af678a914` / 169 tables, container `6f826ade371a`, its image/config/start time
and restart count, every environment/worker flag, credentials, private boundary,
permissions and CSP remain unchanged. No database write, migration, provider
request or publication was requested by this release. Business rows were not
read or frozen; existing background activity remained live.

## Evidence

- [Final status](final-release-status.json) contains aggregate geometry and pins.
- [Captured baseline](baseline.json):
  `6c8dcf5954a5ccac79b323dc40a67e001034e232d27505a55d101c451a103216`.
- [Independent prepared review](prepared-review.json), canonical prepared receipt:
  `1958c97791a8785ed95e65f6548486f761a09b8c9fddd561ec432e7571e31e4d`.
- [Deployed transport receipt](deployed-envelope.json), independently recomputed:
  `a921c62e832ed0ede42409f3dab590303bfb5547af06addf7d30c2468c5bd5e4`.
- Static inventory:
  `23de6e842828ec137b75abbdf36663b77f1c3f2a69f59970c5dbbacb2a5caa30`.
- Nginx config:
  `a8cbd5556d10436ef38351c075d87c1a98253ed766f5289f911aec703b8c007d`.

Canonical server receipt encoding is sorted JSON, indent 2, trailing LF; exclude
`receipt_sha256` from transport envelopes when recomputing that hash. Original
generation-time `executed:false` command manifests remain unchanged.

Root production acceptance used actual scrolling and clicks. At desktop width
1280, the main pane scrolled 627px while navigation stayed at top 93px, height
591px, with its last entry bottom at 465px; that entry was clickable and active.
Previously the navigation height was 2151px and moved to -534px at the same main
scroll. At mobile width 390, document scroll width stayed 390, six navigation
buttons occupied one row, and navigation height was 60px. After main scroll
759px the bar stayed at top 77px; horizontal nav scroll 272px placed the last
button at x248–368, where its click and active state worked. Private screenshots
remain in local outputs and are not included in these public artifacts.

## Guardrails and validation

Capture used two identical immutable samples: exact runtime/source, ordered
environment, private and credential metadata, 169 table definitions, immutable
DB pragmas/inode, static files, Nginx and CSP. It loaded the published helper
once and never called the legacy mutable sample after public-root adaptation.
The payload contains `static/` files only, with all other application source
protected by inventory. Prepare made no active-site change.

The focused suite passed 97 tests plus six subtests; independent read-only review
passed. Recovery accepts only known old/new config bytes, cleans only their known
prefix temporary files, always reloads the old configuration even after a prior
reload failure, and verifies the old frontend plus CSP on the live loopback
listener before claiming success. Unknown configuration is never overwritten.
No database restore or backend lifecycle operation is part of this recovery.

All cloud actions and production UI acceptance were performed by the root agent.
The release-tool author performed local preparation and audit only, with no
commit or provider request. Real publication remains subject to owner approval.
