# Merchant industry label follow-up

This release extends only `app/backend/services/merchant_industries.py` and its
focused test coverage. It maps observed beauty-service aliases into the existing
`美业` classification when reading/filtering records. No database row backfill,
schema migration, frontend change, ownership change or assignment is performed.

The reviewed baseline is carrier `b63b8888f1d14aa53289eed69e1b00374a6cbddb`,
deployed source `4f62e3dc7b5d9e3edd25404f5cb704bc865e0bc3`, frontend
`18302b0ab935`, schema head `e6c0b4f8a916`. Re-check the live container, nginx,
and private runtime before using this recipe; its pins reject any live drift.

`build_payload.py` requires the exact committed HEAD and scopes its source delta
to the service plus focused tests. It takes the exact prior static bytes from the
baseline carrier archive instead of rebuilding UI. Server preparation separately
verifies that every static-file hash and frontend version matches the prior
protected manifest. Only the single backend service is copied onto the pinned
current image.

From the repository root:

1. Run the focused backend tests and commit the source/test change.
2. Freeze the package with
   `python3 deployments/merchant-industry-labels-20261014/build_payload.py --source <full-source-sha> --out deployments/merchant-industry-labels-20261014/artifacts`.
3. Run `python3 -m unittest discover -s deployments/merchant-industry-labels-20261014 -p 'test_*.py' -v`.
4. Review and commit the helper/artifacts as a separate carrier commit, then generate
   the preparation command with `make_commands.py --carrier <full-carrier-sha>
   --preflight <reviewed-server-private-pins.json> --preflight-sha256 <sha256>
   --out outputs/merchant-industry-labels-20261014`.
5. Through the authenticated console, execute preparation. It rehearses the new and
   current rollback images on an offline database copy, requires exact business
   schema/row digests, checks unchanged private API/worker/environment/schema, and
   stages the unchanged static files under a fresh root.
6. Independently review the preparation receipt. Save exact server `prepared.json`
   bytes locally, then add `--prepared-receipt <local-exact-receipt.json>` to generate
   pinned activation and interruption recovery commands.
7. Activate once. The same runtime/data/private checks run again before guarded
   backend/static publication. Failure restores the retained original CRM and
   static configuration without restoring or writing the database.

Verify the live industry facets and filters after publication. Existing original
industry values and raw imported payload remain in the database. Current restaurant
records already display the canonical label; no further classification write is needed.
