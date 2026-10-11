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
  Default monthly reservations are 100,000 characters AND 100 requests. These
  are application usage ceilings, not a provider invoice or dollar spend cap.
  Duplicate requests use a lease; failed/uncertain calls are not refunded.

## Required activation decisions

The prior Google Translation permission does not authorize OpenAI. Do not send
real email to OpenAI, reuse CRM keys, create credentials, enable paid billing,
or deploy an enabled configuration before explicit owner consent covering:

1. Selected mail title, snippet and readable body (excluding attachments) sent
   to OpenAI for this brief, with normal provider data controls.
2. A dedicated private-service API credential, an explicit model and agreed
   paid usage/budget. Never use a Codex runtime credential or APP_AI_KEY fallback.

Only the private API process needs the key. The worker has no AI/batch/scheduled
processing. Required settings after approval:

```dotenv
PRIVATE_MAIL_BRIEF_UI_ENABLED=true
PRIVATE_MAIL_BRIEF_ENABLED=false
PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT=false
PRIVATE_MAIL_BRIEF_PROVIDER=openai
PRIVATE_MAIL_BRIEF_OPENAI_API_KEY=
PRIVATE_MAIL_BRIEF_MODEL=
PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT=100000
PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT=100
```

`ENABLED` and `EXTERNAL_CONSENT` default false; absent or invalid configuration
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

## Verification in this implementation

All network tests use synthetic mail and mock transports. Provider tests cover
structured response/refusal/incomplete handling, evidence validation, monetary
currency mismatch and fake deadlines. Service tests cover owner/source/account
boundaries, atomic reservations, concurrent leases, cache hash validation,
reconnection/disconnection races and financial-field preservation. Standalone
app tests exercise real auth SQL with a separate synthetic readonly CRM sentinel.
Frontend tests cover explicit click, no eager AI, no translation fallback, logout
race handling, escaped output, and detail-only body/quotation boundaries.

Final checks: 499 private backend tests and 70 frontend mail/API tests passed;
TypeScript check and Vite production build passed. Actual component previews at
390px and 1366px had no horizontal overflow. All preview messages are fictional.

The API uses `store:false`, no tools, no redirects/proxies and no automatic
retry. This is not a promise of zero provider retention; structured output and
verbatim anchors cannot guarantee every summary is semantically correct.
Official references:

- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
- https://developers.openai.com/api/docs/guides/your-data

Status: code and synthetic validation prepared; no real AI call, environment
activation, credential creation, push or production deployment has occurred.
