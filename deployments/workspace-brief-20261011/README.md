# Owner private workspace brief — 2026-10-11

Status: implementation and synthetic/local verification only; not pushed, deployed or enabled against real OpenAI data.

## Authorized scope

The owner approved OpenAI mail processing at a monthly USD 5 budget and then confirmed implementation of the full private-space brief proposal. This release prepares today/last-seven-days local summaries and optional explicit-click AI interpretation for Gmail, Google Ads, imported Stripe events, bank email reminders and personal tasks. Customer CRM financial data and calculations remain separate. Existing integration and email consent must not silently stand in for the new runtime workspace disclosure gate.

## Behavior

- GET `/api/v1/private-workspace/brief?period=today|last7days` reads only this owner's independent private records. It performs no connector synchronization, mail-body fetch or AI request.
- The system ranks at most three actionable items. Platform state, source coverage and numbers remain deterministic and are not supplied by the model.
- POST `/api/v1/private-workspace/brief/explain` accepts only a period and current snapshot id. A changed or expired snapshot fails closed. Cached explanation can be read without another request.
- The owner explicitly opens a proposed personal task, reviews its editable title/notes/priority/date, then saves. Reading a brief never creates tasks, replies, payments, bank entries or ad changes. AI prose never fills task drafts.
- All sources retain their individual sync times. Missing or stale coverage is not zero activity or a healthy account. Ads dates retain the original account timezone and complete-day window; partial Ads snapshots require verification instead of asserting a current anomaly.
- Stripe counts are bounded imported events by creation date and currency, not account totals, revenue, bank receipt or profitability. Historical failure/dispute statuses require a fresh platform check. Bank information is an unverified email reminder, not direct bank access.
- Today and the last seven calendar days are labeled in Beijing time; Ads metrics retain their distinct original period. Period changes, session changes and local freshness checks reject stale UI responses.

## Optional AI and approved shared budget

`PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT=false` is new and defaults false. It must be verified independently before activation, alongside all mail provider enable/key/host controls. Nothing in this release toggles runtime consent or enables a provider.

The minimized AI input contains system-generated source summaries, counts/facts, limitations and already-ranked issue ids/actions. It excludes original email titles/bodies/attachments, account labels, URLs, raw connector events, payment amounts, bank balances and credentials. No CRM records are read or supplied.

The pinned OpenAI model and dedicated private key reuse the mail provider's fixed endpoint, no-tools setting, no redirects/proxies, no automatic retries, strict schema and `store:false`. This setting is not a promise of zero provider retention. AI may only add separately labeled, number-free Chinese review prose; it cannot replace system facts or change issue ranking.

Mail and whole-space interpretation share **one** owner/month `private_mail_brief_usage` ledger and the approved maximum USD 5, with atomic USD/character/request reservations, conservative failure holds, token-verified settlement and same-month lease receipts. No second USD 5 allowance or unrelated hosting spend is authorized. Project-provider controls are supplementary, not a substitute for the application limit.

## Isolation and activation prerequisites

The feature adds only `private_workspace_briefs` to the independent PrivateWorkspaceBase database, bringing its exact table inventory to nine. Preserve the other eight tables and all original rows/indexes, credentials, generations and stored source data. No business Base, business migration, customer finance startup or CRM backend configuration is changed.

Before a future authorized deployment, reconcile the live backend/container/static baseline; verify owner-only access and readonly CRM identity mount; back up and verify old private columns/rows; migrate only the private schema; retain rollback images/assets; check original CRM container/configuration and finance table fingerprints. Old release scripts that enforce exactly four tables are obsolete and must not be bypassed silently. AI keys belong only to the eligible API workload, not the sync worker or browser bundle.

The currently inspected Aliyun private service host is in Hong Kong. Do not enable direct OpenAI calls there, hide its location through a proxy, create or reuse unrelated credentials, or purchase new hosting under the USD 5 API allowance. Actual activation requires an eligible OpenAI account, a dedicated project/key and a legitimately deployed AI workload in a supported region. Neither these prerequisites nor real model output have been verified in this implementation.

## Validation

All provider requests in tests use synthetic transports; all browser previews use fictional local records. Exact private-table inventory and the CRM-file/financial sentinel remain verified. Full private backend suite: 582 passed. Frontend API/Ads/mail/brief suite: 100 passed. Application TypeScript check, focused ESLint and final Vite production build passed. The real component was visually checked at desktop 1366 x 950 and mobile 390 x 844; 320 x 740 also has no horizontal overflow and retains its fixed private navigation with reserved content padding. These are local/synthetic results, not production acceptance or real OpenAI output.
