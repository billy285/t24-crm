# Sales calling controls static release

The exact app allowlist is `pages/SalesWorkbench.tsx`,
`components/SalesCallRecord.tsx`, and `pages/sales-calling-controls.css` under
`app/frontend/src/`, plus focused frontend tests. This release opens the existing
eight call outcomes, fixes quick-edit/navigation clipping, and preserves the
full quality-filter label. It does not add AI scripts, change import templates,
or change financial/private/customer permissions.

Baseline carrier is `74b1cf1cd96e4880301dfa7e4c40e72acc8cad1e`, deployed app
source `c8f595126bf48108bbbc1637a3de1e3d4bff8bd5`, frontend `18302b0ab935`.
The current CRM runtime, private roles/environment, both DB identities/schemas,
nginx hash and static root must pass authenticated live review before publication.

1. Finish scoped UI tests and frontend build, commit source/test changes, then run
   `build_payload.py --source <full-source-sha> --out deployments/sales-controls-20261014/artifacts`.
   The builder checks all committed app bytes and rejects changes outside the
   allowlist; every preserved backend, finance/private and other frontend source
   stays in the immutable manifest inventory.
2. Run `python3 -m unittest discover -s deployments/sales-controls-20261014 -p 'test_*.py' -v`.
   Review and commit frozen helper/artifacts as a separate carrier.
3. Use `make_commands.py --carrier <full-carrier-sha> --preflight <reviewed-private-pins.json>
   --preflight-sha256 <sha256> --out outputs/sales-controls-20261014` to generate
   immutable acquisition and preparation commands without executing them.
4. Execute preparation through the authenticated server console after live
   baseline verification. It stages a fresh static root and keeps existing hashed
   assets available for open tabs. It leaves nginx, CRM and private services running.
5. Independently review the receipt. Save the exact server `prepared.json` bytes,
   then add `--prepared-receipt <local-exact-receipt.json>` to generate pinned
   activation and interruption recovery commands.
6. Activate once. Only nginx static-root configuration changes, using compare and
   replace plus config-test/reload. Public assets/version and runtime/data-boundary
   checks run after publication. Failure restores only the prior static root.

No Docker build, container creation, restart, database migration, environment
mutation, SQL update or DB restore occurs in these release phases. Normal business
row activity is allowed while file identity, schema and every container runtime
must remain unchanged. Verify desktop/mobile outcomes, quick-edit and queue filters
after publication; production records need no test writes.
