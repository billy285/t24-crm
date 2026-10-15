# Sales Center unified merchant dossiers

This release adds one current prospect dossier, cumulative sales history, manual follow-up summaries, owner invitations, handoff acknowledgement and durable phone contact protection.

## Boundaries

Only the explicit sales source allowlist is overlaid on the exact deployed CRM image. Existing finance formulas, month closing rules, commission attribution, customer invitation rules and private-workspace source files are outside the allowlist. No invitations are created during deployment.

Seven new sales-only tables are added by `e6c0b4f8a916` -> `f7d1c5a9b027`; existing tables and rows are preserved. Original merchant imports remain evidence. Their list uses latest scoped lead data where authorized. Prospect creation uses retained ID maxima to avoid reattaching historical records after legacy deletion; dossiers with history cannot be physically deleted.

## Release steps

Build and test the exact committed source, freeze the approved frontend/backend payload with `build_payload.py`, then commit the immutable carrier. `make_commands.py` creates acquisition, preparation, activation and recovery commands with SHA-256 pins. Run preparation and independently inspect its receipt before activation.

Preparation builds offline from the exact deployed image and rehearses migration/startup on an isolated copy. Migration requires the CRM container to be confirmed stopped and hashes every original row and schema definition. Private API and worker are never restarted. Sensitive environment files and database copies are excluded from Docker build context. Public files receive only the required read permissions.

Recovery never restores a database snapshot. Before migration it may resume the retained original CRM; after the new schema commits it can only resume the reviewed new image. A failed forward recovery does not fall back to old code. All actions retain protected receipts.

The server checkout has previously retained local frontend changes; this release never resets or edits that checkout and instead verifies immutable running-image file inventories.
