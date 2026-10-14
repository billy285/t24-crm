# Customer collaboration by owner invitation

Release scope: explicitly invited internal employees only; default basic information and deal business records read-only. Customer finance is independently granted to an active invitee. Existing grants migrate to pending review. No ownership or department inheritance remains. UI supports batch invitation, revocation, per-module permissions, and a separate preview step.

## Preserved boundaries

No company finance formulas, closing conditions, commission attribution, or private workspace implementation is changed. Migration d5b9a3e7f815 only adds five invitation provenance/state columns; existing rows and old values are hash-compared before and after migration. Existing explicit grants are not silently converted to active invitations.

## Release process

1. Freeze application changes at a source commit and build Vite from it.
2. Run build_payload.py with that exact commit. It rejects any source change outside the backend/frontend allowlists and test files, as well as build/source version drift.
3. Commit the payload manifest and release helper as a carrier; download only immutable commit URLs, checking sizes and SHA-256 on the server.
4. Prepare against the exact deployed CRM container, nginx configuration, and private service boundaries. Rehearse migration and startup on an offline database copy with network disabled.
5. Review the prepared receipt independently before activation.
6. Stop only CRM, perform the additive migration, compare all pre-existing rows, and start the reviewed image. Switch the CRM static root and verify public readiness/version.

Private API, worker, credentials, and database schema remain pinned and unchanged. Business database snapshots are never restored. If migration commits, recovery must use the reviewed invitation build; legacy authorization code is forbidden. Unsafe automatic restart policies on the old CRM container block the release. nginx recovery removes only validated temporary files owned by this release.

## Validation

- Invitation and affected business endpoint regression: 180 passed.
- Frontend invitation and commission workflow checks: 32 passed.
- New and retained deployment checks: 122 passed.
- Full backend run: 1,752 passed; all 40 failures and 4 fixture errors reproduced on baseline a40d8236b4bf77ef8694bd6df6ff16b1bd72254f, with no new failures.
- Vite production build passed. Existing Finance.tsx:5750 type mismatch remains outside this scope.
- Actual component QA: desktop and 390px mobile, multiselect invitations, batch previews, separate finance, business-only deal fields, no horizontal overflow.

No production employee grants are altered by UI acceptance tests. Owner must explicitly re-invite legacy collaborators after release.
