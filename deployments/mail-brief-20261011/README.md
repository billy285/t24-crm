# Private mail brief: implementation prepared, real processing disabled

This release adds a single-click Chinese work brief for Gmail in the existing
owner-only private workspace. It does not change business finance calculations,
CRM tables, bank verification, Google Ads mutations, or email scopes.

## Behavior

- Read the selected Gmail message using the existing `gmail.readonly` grant,
  rechecking the actual account and omitting attachments.
- Produce a Chinese title, summary, up to three evidence-backed points, a
  suggested next action, and why the mail may matter.
- Display extracted deadline wording as unconfirmed. Never compute a date,
  timezone or calendar reminder from the model output.
- Keep the imported rule grouping, amounts, currency and due date unchanged.
- Cache the original body and result encrypted in the separate private DB;
  list responses contain no original body or source quotations.
- Bound source text to 27,000 characters and output to 1,800 tokens per request.
  Default monthly reservations are 100,000 characters AND 100 requests AND
  USD 5.00. All three checks must pass in one atomic private-DB update before
  an OpenAI call. Duplicate requests use a lease and cached results cost no
  additional AI request. Failed/uncertain calls retain their full reservation.

## Approved scope and budget

On 2026-10-11 the owner confirmed OpenAI processing for selected Gmail mail
and a monthly USD 5 budget. This approval covers mail title, snippet and readable
body, excluding attachments, for Chinese private work briefs. It does not
authorize disclosing Google Ads, Stripe, bank, calendar or CRM data to OpenAI.
The later request for whole-workspace summary suggestions remains a proposal.

The approved model is exactly `gpt-4.1-mini-2025-04-14`, standard service tier,
at the reviewed USD 0.40 / million input tokens and USD 1.60 / million output
tokens. Unknown aliases, rates or models fail closed. The private application
reserves 421,911 micro-USD before each new call: the published entire 1,047,576
token context at full input price plus 1,800 maximum output tokens, rounded up.
Local UTF-8/token estimates are informational, not the hard budget proof.
Only a fully validated successful usage record may settle the reservation lower;
unknown or failed calls retain the bound. Cache reads never reserve again.

The monthly ceiling cannot be configured above 5,000,000 micro-USD. Accounting
uses UTC calendar months. This limits this feature's reservations and verified
usage, not unrelated spending on an OpenAI account, taxes or a hosting invoice.
Use a dedicated API project/key and its available project spend control too;
provider enforcement alone may lag. Do not purchase hosting or increase budget
under this approval.

## Remaining activation prerequisites

Owner mail/budget consent is now present. Runtime activation is still disabled
until a dedicated key, an eligible account and supported-region hosting have
been verified. The current Aliyun server is in Hong Kong, which is absent from
the official OpenAI supported-country/region list checked on 2026-10-11. Do not
enable direct OpenAI requests there or hide the location through a proxy. A real
AI workload deployment in a supported region must be arranged and authorized;
the existing CRM financial service is not moved or modified by this release.

Do not reuse CRM keys, a Codex runtime credential or APP_AI_KEY fallback. Keep
private credentials out of the browser bundle, outputs and command logs.

Only the private API process needs the key. The worker has no AI/batch/scheduled
processing. Required settings after approval:

```dotenv
PRIVATE_MAIL_BRIEF_UI_ENABLED=true
PRIVATE_MAIL_BRIEF_ENABLED=false
PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT=false
PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED=false
PRIVATE_MAIL_BRIEF_PROVIDER=openai
PRIVATE_MAIL_BRIEF_OPENAI_API_KEY=
PRIVATE_MAIL_BRIEF_MODEL=gpt-4.1-mini-2025-04-14
PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT=100000
PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT=100
PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD=5000000
```

`ENABLED`, `EXTERNAL_CONSENT` and `HOSTING_VERIFIED` default false; absent or invalid configuration
fails closed before Gmail body fetch or AI HTTP. Neither setting can be changed
through the public API. UI capability failure also makes no third-party calls.
Legacy Google translation can be selected only by explicitly setting
`PRIVATE_MAIL_BRIEF_UI_ENABLED=false`; it is not an automatic fallback.

## Isolation and release checks

Reconcile the current server/container and static release first. Build a new
private API candidate; do not restart, recreate or migrate the CRM backend.
The private schema now has eight tables: the original four, two translation
tables from the prior undeployed change, and `private_mail_briefs` plus
`private_mail_brief_usage`. Add these only to the private DB using its own Base.
Do not copy secrets or mail text into release artifacts or command logs.

Before switching, verify owner-only access with live revocable sessions, readonly
CRM identity mount, independent private DB, actual Gmail mailbox, fixed endpoint,
new ciphertext fields and cache generation invalidation. Preserve the original
CRM container/configuration/table fingerprints. Retain rollback image and static
assets. Existing older release scripts which require exactly four private tables
are not suitable for this candidate and must not be silently bypassed.

The budget migration is limited to fixed private brief/usage columns. Previously
recorded nonzero usage without a USD reservation must conservatively exhaust
that historical monthly budget; it must never be treated as zero-dollar usage.
Preserve every original private table, index and row, and verify the CRM sentinel
and production fingerprints before and after any later authorized release.

## Verification in this implementation

All network tests use synthetic mail and mock transports. Provider tests cover
structured response/refusal/incomplete handling, evidence validation, monetary
currency mismatch and fake deadlines. Service tests cover owner/source/account
boundaries, atomic reservations, concurrent leases, cache hash validation,
reconnection/disconnection races and financial-field preservation. Standalone
app tests exercise real auth SQL with a separate synthetic readonly CRM sentinel.
Frontend tests cover explicit click, no eager AI, no translation fallback, logout
race handling, escaped output, and detail-only body/quotation boundaries.

Final checks: 556 private backend tests and 73 frontend mail/API tests passed;
TypeScript application-project check and Vite production build passed. Actual component previews at
390px and 1366px had no horizontal overflow. All preview messages are fictional.

The API uses `store:false`, no tools, no redirects/proxies and no automatic
retry. This is not a promise of zero provider retention; structured output and
verbatim anchors cannot guarantee every summary is semantically correct.
Official references:

- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
- https://developers.openai.com/api/docs/guides/your-data
- https://developers.openai.com/api/docs/models/gpt-4.1-mini
- https://developers.openai.com/api/docs/guides/spend-limits
- https://developers.openai.com/api/docs/supported-countries

Status: owner consent recorded; code and synthetic validation prepared; no real AI call, environment
activation, credential creation, push or production deployment has occurred.
