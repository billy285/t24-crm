# Private Gmail Chinese reading

Status: implementation prepared; production enablement is pending the owner's separate billing approval, Cloud Billing association, restricted translation credential, and live acceptance. No translation key or real mail content belongs in this directory.

## Scope

- Owner-only private Gmail: Chinese titles/snippets, explicitly requested body translation, original/Chinese switch.
- Google Cloud Translation Basic v2 NMT, target `zh-CN`, fixed endpoint and header API key. Attachments, HTML execution, remote images and dynamic endpoints are excluded.
- Existing Gmail read-only OAuth is reused; the mailbox is checked against both the connected identity and `PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT` before a body is read.
- CRM financial code, data, migrations and the CRM service are outside this change. All new persistence uses `PrivateWorkspaceBase` and the independent private database.

## Server-only configuration

Use the existing protected private service environment file. Never add these values to a browser bundle or the CRM service environment.

| Setting | Required value |
| --- | --- |
| `PRIVATE_MAIL_TRANSLATION_ENABLED` | `true` only after billing and credential setup are approved and verified; omitted means disabled |
| `PRIVATE_GOOGLE_TRANSLATE_API_KEY` | Dedicated key restricted to the Cloud Translation API and the verified server egress IP |
| `PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT` | `100000` for the proposed approved limit; do not raise without a new spending decision |

Billing must be enabled for the Google Cloud project. The published free allowance may be shared by other Translation calls. The application therefore does not assume zero cost. At the published Basic NMT rate of USD 20 per million characters, 100,000 characters corresponds to approximately USD 2 before any free allowance, taxes or unrelated Google services. Source: https://cloud.google.com/products/translate/pricing

## Persistence and limits

Two additive private tables: `private_mail_translations` (Fernet-encrypted text, cache state and short processing lease) and `private_translation_usage` (owner/month atomic character reservations). Private database table count becomes six; no existing CRM table is changed.

Cache keys bind the owner, verified mailbox, connection, generation, message, source hash, mode and translation version. A disconnect/reconnect invalidates use of old caches. A response is guarded against connection or original-content changes while processing.

Reservations count the actual characters sent, including whitespace, by UTC calendar month across reconnects. Failed or ambiguous calls keep their reservations. There are no automatic retries or refunds. First entry requests at most ten snippets; additional batches require an explicit click. Bodies are read only on request, capped at 50,000 characters with visible truncation. Cached bodies do not consume additional characters even after the monthly limit is reached.

## Release checklist

1. Obtain the outstanding billing decision; the user completes any billing-account/payment setup. Confirm applicable API terms and new credential access at action time.
2. Reconcile current server, repository and public release state. Preserve a private database/environment backup. Do not reuse stale deployment fingerprints.
3. Build and test a private-only candidate image, including the six-table private schema and owner/session denial tests. Run the frontend build and translation UI tests.
4. Install the dedicated restricted key only in the protected private runtime environment. Verify outbound egress and restriction before enabling real mail translation.
5. Replace only private API/worker containers; keep the CRM container ID, image, start time and configuration unchanged. Publish the scoped frontend assets with prior static assets retained for open clients.
6. Validate one owner-visible synthetic translation and then a small owner-authorized mail preview; verify cached repeat requests do not increase reservations. Verify original/body toggle, mobile wrapping, non-owner denial and unchanged CRM financial tables.
7. Record exact image/source/frontend identities and acceptance results. Do not describe the feature as deployed or connected until these checks pass.

Rollback: disable the translation flag first. A previous private image/frontend can be restored; the two additional private tables may remain unused. Do not delete mail, credentials or usage records as part of rollback.
