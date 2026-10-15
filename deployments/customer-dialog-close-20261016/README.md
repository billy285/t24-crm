# Customer dialog close-button repair

This package publishes only the frontend build from source `b2655953a2d909ba3fd79dd37e7dddbe4dfc54bd`, version `3361045efa5f`. The application diff against `df6c86e8a821bef26cd2e4d6a960fc93fa55002d` is exactly `app/frontend/src/pages/Customers.tsx` plus `app/frontend/tests/customers-dialog-close.spec.ts`. The close button receives a higher stacking order within the existing Add/Edit dialog. No permission, calculation, record, or confirmation behavior changes.

The helper never builds, stops, replaces, or restarts a container. It never changes the backend, environment, SQLite data/schema, private service, or private files. The only live change is an atomic replacement of the exact pinned nginx frontend root followed by nginx validation/reload. All other nginx bytes must remain identical. The previous public directory remains intact, and its old hashed assets are copied into the new directory so existing browser tabs can load their chunks.

Before preparation and activation, the helper checks the exact host, root ownership, retained utility hash, existing CRM container/image/configuration, full database schema digest and revision, private boundary, original public-file inventory, frontend version, and nginx bytes. Only the retained helper's read-only private/runtime/schema/public-check utilities are used. Its old publishing, migration, container replacement, and database restoration functions are never called. Running business transactions may continue; this package opens the business database read-only and does not freeze or restore business rows.

Preparation creates a fresh protected release directory and a fresh public directory at `/var/www/t24-crm-public/customer-dialog-close-b2655953a2d9-20261016`. It verifies every payload file, preserves old assets, and writes a receipt without changing the active nginx configuration. Activation requires an independently reviewed exact-byte `prepared.json` hash, then rechecks all boundaries and the complete prepared public inventory. A failed activation restores only the exact previous nginx bytes; it never restores a database or restarts an application. Unknown nginx edits or unrecognized temporary files stop recovery. A successful release cannot be reverted through the interrupted-activation recovery command without a separate review.

Build and verify locally from the frozen source HEAD:

```sh
python3 -B deployments/customer-dialog-close-20261016/build_payload.py \
  --source b2655953a2d909ba3fd79dd37e7dddbe4dfc54bd \
  --out deployments/customer-dialog-close-20261016/artifacts
python3 -m pytest -q deployments/customer-dialog-close-20261016/test_release.py
```

Commit exactly the helper, builder, command generator, tests, this README, and the two artifacts under this directory as a separate carrier commit. Do not include caches or application changes in that carrier. After pushing and reviewing its immutable SHA, generate acquisition commands without executing them:

```sh
python3 -B deployments/customer-dialog-close-20261016/make_commands.py \
  --carrier REVIEWED_40_HEX_CARRIER_SHA \
  --preflight /opt/t24-crm/releases/commission-service-month-preflight-20261013.json \
  --preflight-sha256 af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161 \
  --out outputs/customer-dialog-close-20261016/commands
```

The generated preparation command downloads only the three release members from the exact Git carrier, rejects redirects, checks exact lengths/hashes, and executes the pinned helper. Save the server's `prepared.json` **exact bytes**, review its source/version, current CRM identity, unchanged-boundary flags, and public-inventory digest independently, then run the generator again with `--prepared-receipt /absolute/path/prepared-receipt.json` to generate activation and guarded recovery commands. A JSON stdout wrapper is not a valid prepared receipt.

After activation, verify the public version and real Add/Edit close-button interaction in both desktop and mobile browsers. Keep the old public directory and all receipts for recovery evidence. This package contains no credentials and performs no provider or customer communication.
