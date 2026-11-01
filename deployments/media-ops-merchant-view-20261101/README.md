# Merchant-first media operations release

This release adds the local, read-only merchant projection and the reviewed frontend. It preserves all 150 populated tables, every existing environment value and credential boundary, current customer/provider permissions, financial logic and private workspace. Meta execution and scheduling remain off. Google scheduling retains its existing cutoff.

`preflight.py` loads the exact previously deployed helper and captures two stable samples of runtime, source, full table hashes, schema, environment digests, credential metadata, private boundary, Nginx and static inventory. It never opens credential-file contents or sends provider requests. The actual protected proof is pinned in `release.py` and `build_payload.py`.

Frozen application source: `5a904dd925f03296c07018f83e97277f5f90dd08`; frontend: `42de3d4757db`; application freeze: `a57d42847bddadf58947edefab63b654bdcd37bc55227bae38bbe23f1fbcb168`. The exact delta contains 20 files: two new backend modules, 12 frontend runtime files and six tests. All 103 deployment-tool tests pass. The generated package has 142 members (two backend modules and 140 static files). Final immutable-carrier staging still requires the root agent’s committed carrier SHA and independent review; no live phase has run.

The package builder validates the complete committed application tree against the prior deployed source, requires the exact reviewed delta, rejects deleted baseline files, and includes only the two new backend modules and full reviewed static tree. Artifacts use a fresh, private output directory with pinned directory descriptors and exclusive writes.

Preparation overlays the two new modules on the exact current image, without dependency installation, environment changes or migrations. An isolated copy of every populated table runs with no network, credentials or workers. It verifies Python 3.10, the exact two GET routes through OpenAPI and lazy route contexts, sales/finance denial before database access, existing route/capability guards and unchanged rows, schema and database metadata.

Switching requires a separately reviewed canonical server `prepared.json` hash. The created candidate ID is fsynced before stopping the original container. Every boundary rechecks current data, source, full environment, credentials, private workspace, original static tree and complete new static tree. Only the single Nginx static-root value changes; existing callback/media privacy blocks and CSP stay exact.

Recovery first contains the known durable candidate. It restores the original compatible runtime and static root without restoring the database, dropping tables or deleting production containers, preserving independent business changes. A completed deployment requires separate recovery review.

Run synthetic tests locally:

```text
python -m pytest -q deployments/media-ops-merchant-view-20261101
```

Only the root agent executes reviewed commands against the authenticated target. These tools do not authorize any real post, comment reply or scheduled publication.
