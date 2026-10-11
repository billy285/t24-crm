# Private workspace clarity UI release

The user authorized publication of the reviewed private workspace layout on 2026-10-12. The frontend source is `8e1c07415e78db6b9ef199e997e501d1db4dc5e6` and the built version is `ecae2d8aa23a`.

The release changes priorities, cached funds navigation, period control layout, mail/advertising reading flows, and responsive detail sheets. It contains 22 frontend source/test changes and 113 built files. The CRM finance page, backend, provider access, credentials, private bank/Stripe calculations and API contracts are unchanged. No provider sync or AI processing is part of deployment.

The accepted live baseline is the currency UI release `adfb31c0b755`, with private backend `c1ae19b38fec8f62f044d4b0789f31662da12fbf`. The authenticated server preflight confirmed this baseline and healthy CRM/private API services. The older `/opt/t24-crm` checkout has pre-existing frontend changes and is not used or modified by this publisher.

Local verification completed: 212 private frontend tests, TypeScript checking, production build, and UI checks at widths 320, 390, 1024 and 1440. Source, build output, manifest and archive hashes were independently reconciled. Simulated local preview data is not production account data.

The publisher requires the fixed host, exact frozen artifacts, original backend evidence and the current currency static receipt. It uses a new protected release directory and public directory, retains prior assets, and switches only the Nginx static root. It rechecks runtime, schema, authorization and stable private records; it rolls back to the currency release if publication checks fail. Published success must additionally be checked in the authenticated owner UI.

The first publication attempt was safely rejected because the encrypted authorization fingerprints differed from the accepted historical receipt. A subsequent read-only server diagnosis found only normal Gmail and Google Ads `access_token` and `expires_at` refreshes; owner, account, scope, generation and OAuth state fields were unchanged. The failed directory remains preserved. The retry uses the fresh fixed directory `/opt/t24-crm/releases/private-clarity-ui-8e1c07415e78-20261012-retry2` and retains the currency release as its rollback target.

The refresh exception requires the original private backup hash to match the pinned backend receipt, its reconstructed full authorization map to match both accepted owner and currency histories, and the current full map to remain exact throughout publication. Only existing connected Gmail/Google Ads OAuth credentials may differ. Their decrypted key sets must be identical; only `access_token`, `expires_at` and an already-present `expires_in` may change. Refresh tokens, scopes, account identity, all other credential values and types, and all bound connection identity/permission/generation/OAuth fields remain exact. Any other change rejects publication; another refresh inside the publication window also rejects it or triggers a static rollback.

The credential comparison uses read-only SQLite connections and a bounded stdin-only probe in the same pinned healthy private API container. It performs no provider request, database write, credential rewrite or backend restart. Proof records contain only hashes, source names, counts and changed field names; ciphertext, token values and subprocess error output are never logged. The probe proves stored identity and permission fields are preserved; it does not query a provider to establish the refreshed access token's remote identity. Offline regressions cover real local SQLite/Fernet evidence, history/backup mismatches, credential and scope changes, identical key sets, concurrent refresh rejection and stdin-only transport.

Frozen artifact hashes:

- Manifest: `19b6b72ed7db9bfc52821777a511381f77035a4974cd89863ed1b9969f56d210`
- Payload: `51c5e12784dca30be0a0b5c4ba819fa5dcf6cec61ad8bb20d8d6be65d9b25d90`
- Prior static receipt: `dd7ccc6ee0d4273a281a7fb579ea871287305d41142b0363bc1624779ddeae48`

Preparation and offline testing do not prove production publication. The server result and owner UI evidence are recorded separately after execution.
