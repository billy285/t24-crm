# Meta monthly action layout: static-only followup

This release fixes the real desktop monthly-action button clipping found after the main Meta monthly deployment. Only compact display labels and responsive action-cell layout change. The original next-action data, run / platform / merchant navigation, permissions and backend calculations are unchanged.

The immutable backend baseline is the completed Meta monthly application `5fd379d625d6c18abdec1b98d388494d0900c780`, deployed receipt `41ab8e9a87761901e16cce56102de6040d80476aa1b9e43c9f422cea1e3d3aa0`, frontend `1d94d63752de`, runtime `1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e`, with 420 backend runtime files and unchanged schema `g32ed456e792` / 162 populated tables.

A fresh two-sample read-only capture pins the exact canonical baseline, runtime, all source and table hashes, schema, environment, credential metadata, private boundary, Nginx and CSP. It writes only a new root-private aggregate proof and never contacts a provider.

Freeze requires the exact committed three-path frontend / test delta, every other application path unchanged, and the reviewed matching build. The deterministic payload contains static files only and preserves previous hashed assets. The carrier is immutable and source checked; prepare and activation are separate commands with a separately reviewed canonical prepared receipt.

Prepare only stages a new public directory. Activation substitutes exactly one Nginx static-root byte sequence, reloads Nginx and checks public version / CSP and all preserved boundaries. On failure it restores only that root. There is no Docker lifecycle, backend image change, migration, database restore, permission / credential / environment change, public content publication or provider request. The original Meta execution / scheduler switches and cutoffs remain unchanged.

Production UI acceptance is required after the static switch; synthetic layout tests do not substitute for checking the actual desktop screenshot.

## Accepted production state

Canonical deployed receipt: `2354bb6e48c86423250df592434cc5d020020ac397b44f92cd7fef31df836c4d`; current public frontend: `8c3b5e1302ac`. The exact backend runtime and all 162 table hashes remained unchanged. Actual authenticated UI measured desktop action width 122 / scroll width 122, mobile 390 action 224 / 224, and mobile 320 action 162 / 162 with page widths 390 / 320. The authenticated owner session was visually inspected; actions are readable without the duplicated platform prefix. No production data or public content was submitted.
