# Private workspace navigation static release

This release changes only the private workspace's frontend navigation and its UI
state. The accepted private backend remains source
`3c5b8c1d63b8f078e162e228750b508715699479`. It does not migrate, initialize, seed,
restore or write either database, change credentials, or start/stop/restart any
CRM/private service. Bank and external AI remain disabled.

After committing and testing the approved navigation source, freeze the complete
built `app/frontend/dist` with the actual generated frontend version:

```text
python3 build_static_payload.py --repo <checkout> --output <fresh artifacts directory> --source-sha <reviewed source SHA> --version <built frontend version>
```

The local builder rejects unrelated frontend, finance/backend/dependency changes,
dirty tracked source, untracked source files, symlinks, nonstatic files, stale
versions, and existing artifacts. It emits a deterministic archive and a manifest
whose digest must be independently reviewed before upload.

Acquire the exact reviewed `static_only_upgrade.py`, `static-manifest.json`, and
`static-payload.tar.gz` into a new root-owned mode-0700 directory, with regular
mode-0600 files:

```text
/opt/t24-crm/releases/private-navigation-<first 12 source SHA characters>-20261011
```

`acquire_static.py` is standalone and may be executed from its hash-reviewed
inline source before the publisher exists. Its immutable carrier command is:

```text
python3 acquire_static.py --source-sha <reviewed frontend source SHA> --carrier-sha <pushed artifact carrier SHA> --archive-sha256 <reviewed codeload ZIP SHA256> --manifest-sha256 <reviewed manifest SHA256> --payload-sha256 <reviewed payload SHA256> --helper-sha256 <reviewed static_only_upgrade.py SHA256>
```

Only the fixed GitHub codeload origin is used, without redirects or credentials.
The ZIP is capped at 32 MiB; all archive and selected-file bindings are verified
before any file is written. Only the three reviewed files are installed. A small
`acquired.json` contains hashes and release identity, never archive contents.

The authenticated root execution is:

```text
python3 static_only_upgrade.py --execute --frontend-source-sha <full reviewed source SHA> --frontend-version <built frontend version> --manifest-sha256 <independently reviewed manifest SHA256>
```

The publisher verifies the immutable prior carrier's code before importing its
static-only primitives. It pins the accepted backend candidate, final switch and
formal static receipts, the current served version `374558c66144`, and the
existing Nginx root. The frontend SHA/version are separate from backend identity.

It preserves service identity/image/configuration/start/restart count, the
private database's physical identity and ten-table schema, original environment
hash, private owner boundary, and disabled bank/AI state. It does **not** compare
current business/private rows with historical release snapshots. Normal existing
provider syncs continue. The 83 customer tables are compared within this release's
before/after window; any difference rejects acceptance for review.

Only a new public static directory and exact Nginx root change are published.
Previous hashed assets remain readable. Public version, index, reachable asset
graph, security headers, unauthenticated private rejection, and CRM readiness are
verified. Any post-switch failure restores only the previous Nginx root after
checking concurrent changes; late receipt failures also roll back and cannot
claim deployment. A concurrent unrelated Nginx edit is never overwritten.

Local synthetic verification:

```text
python3 -m pytest deployments/private-navigation-20261011 -q
```

Tests never use production databases, authenticated sessions, provider APIs,
browser state, or production services.
