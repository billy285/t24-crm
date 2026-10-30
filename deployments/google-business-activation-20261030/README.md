# Dedicated Google OAuth activation — configuration only

These tools are separate from the frozen disabled Google release. They make no
Google provider requests, do not create a client, do not run migrations or seeds,
and never write the business database. Do not execute an unreviewed command.

Pinned disabled baseline:

- Source: `7431d1986b81328fcc822e3e13641e4d03b6b9bf`
- Frontend: `c648c284143e`; schema: `c8d3e5f6a702`
- Image: `sha256:0a058c4927abd5c2216fe65a8f36a42705d7064ad91248339ca997aa3d019ccb`
- Actual deployed receipt: `16fbbcf5ef322684256fff82af3b25146a5efaff48f7947a398c480020895cab`
- Host: `iZj6c4cj7edgnhdimts4l7Z`; container: `t24-crm`
- Approved project: `t24-beauty-os-20260823` / `58950527996`
- Only callback: `https://t24-crm.com/api/v1/google-business/oauth/callback`
- Only OAuth scope: `https://www.googleapis.com/auth/business.manage`

## Sequence and review gates

1. Independently review `core.py`, `preflight.py` and the generated read-only
   wrapper. Execute only through the authenticated fresh Ali session. The proof
   checks the actual disabled receipt, exact runtime, all 124 tables, empty five
   Google tables, source/static/schema/private pins and active Nginx configuration.
   It exports no environment values or customer records. Its Nginx view preserves
   whitelisted structural/proxy directives; unexpected values are redacted.
   All phases disable process core dumps and use a restrictive umask.
   The separately reviewed `diagnostics` phase is pinned to the observed full
   active configuration hash. It returns only public DNS IPs, Docker log driver/
   option names, APM environment names and sanitized global logging destinations.
   Nonpublic/fake DNS answers are excluded. DNS is not origin-route proof, and
   absent APM names are not proof that no external collector/forwarder exists.
2. Independently review transport code. Run `transport-init`; it creates only
   protected local credential/release directories and one RSA-3072 private key.
   It exports the public key, context and 15-minute expiry. Root creates a new
   dedicated **Web** client in the approved project, preserving existing clients
   and shared project consent settings. Check the project audience/publishing/
   verification state; external Testing refresh tokens expire in seven days for
   `business.manage`. Quota approval does not prove OAuth production readiness.
3. In the trusted browser runtime, call the reviewed `encryptGoogleClient`
   function from `encrypt-in-browser.js`. Pass client ID and secret directly from
   the trusted credential UI into memory; return/print **only its ciphertext**.
   Do not log arguments, screenshots, raw credential JSON, clipboard values or
   browser DOM containing the secret. The compact two-field payload is limited
   to RSA-OAEP's 318-byte plaintext capacity. OAEP's label binds host, approved
   project, callback, expiry, transfer ID and public-key fingerprint.
4. Run `transport-install` with the exact public transfer ID and ciphertext.
   A one-use claim and global install lock prevent replay/parallel overwrite.
   The server validates the client project prefix, generates a new random Fernet
   key, and exclusively creates `/opt/t24-crm/secrets/google-business/runtime.env`
   (`0600`, parent `0700`). It contains exactly six `T24_GBP_*` variables but is
   **not loaded into any runtime yet**. Neither private Google credentials nor
   existing CRM credentials are read/reused. The temporary RSA key is removed
   only after the protected receipt is saved. Claimed failures cannot be retried;
   start a fresh transfer after reviewing the failure. Old expired private-key
   files require scoped operator cleanup; no cleanup worker is installed.
5. Run `plan-nginx` **before any callback/configuration change**. It saves
   protected original runtime/config snapshots and a proposed callback-only
   insertion. No active configuration changes. Review the returned exact hashes,
   narrow safe-view block and log paths. Nonstandard proxies, ambiguous TLS
   servers, nested/rewrite/header/include behavior and debug/external logging
   fail closed rather than guessing. The new exact callback copies only the
   current API upstream/forwarding settings and overrides `access_log off` and
   `error_log /dev/null crit` for this one route. Every existing Nginx byte remains.
   Both plain literal prefixes and the observed `location ^~ /api/` literal
   prefix are supported; regular-expression locations are never guessed/copied.
   V2 artifacts are exclusively created inside the protected
   `/opt/t24-crm/releases/google-business-activation-7431d1986b81-20261030/attempt-v2/`
   folder. Prior root-level plan/review/attempt artifacts are retained. The
   dedicated credential receipt and env file keep their original fixed paths.
6. Obtain independent security review of the full frozen tooling, plan and
   deployment bounds. Fill the `GBP_ACTIVATION_MANUAL_REVIEW_APPROVED` object only
   after actually checking every flag below. No command generator invents that
   approval. Include exact tool hashes, plan hash, project, callback and scope.
   `review_sha256` is SHA-256 of sorted, indented JSON plus the final newline.
7. Generate/run `protect-callback` with the reviewed plan and review hash.
   The tool verifies the active configuration again, atomically inserts the exact
   block, tests/reloads Nginx and makes an unauthenticated **nonsecret sentinel**
   loopback HTTPS callback request. No valid state/cookie exists, so no token
   exchange or business write is possible. It checks the fixed 303/no-store/
   no-referrer response and new Nginx access/error plus container stdout/stderr
   log output. External CDN/WAF/tracing logging requires the explicit manual
   review flag; the tool cannot inspect external logging. Failure restores only
   the exact original Nginx bytes before any OAuth is allowed.
   The receipt binds the full active `nginx -T` hash and complete log-path set;
   enable checks both repeatedly, including immediately before and after switch.
   Log reading is bound to actual supplemental receipt
   `2bda1b6ce27c9b4dec54198e83be5abf5d6d89144da7b5b3330b407a6760e27a`:
   configured `www-data` UID/GID33, exact three observed log paths and their
   individual UID/GID/modes, root-owned parent metadata and one hard link.
   The plan also captures each log device/inode. Worker/owner/group/mode/link/
   symlink/rotation changes fail closed; the tool never changes log ownership.
   The application middleware's Referrer-Policy is overridden only at this exact
   callback: hide the upstream field and add exactly one `no-referrer` field.
   The plan refuses HTTP/server/unknown-include `add_header` or proxy hide/pass
   rules, or custom inheritance settings, rather than dropping their protections.
   Sibling static-location headers remain byte-identical. A no-query baseline
   stores only fingerprints of the other six security headers; every sentinel
   requires those fingerprints unchanged and rejects duplicate Referrer-Policy.
   All curl probes use first-option `-q`, `--noproxy '*'` and fixed loopback HTTPS.
8. After independently reviewing `logging-protected.json`, generate/run `enable`
   with its exact receipt hash. The tool repeats disabled/private/source/schema/
   static checks and sentinel validation; creates a container from the **same
   reviewed image**, preserving all original env values, command, entrypoint,
   labels, mounts, networks and host settings; adds only the exact six Google
   variables. It keeps the disabled original stopped under its reserved name,
   checks readiness/configuration with provider networking explicitly blocked,
   checks all business rows unchanged and records `enabled.json`. Failure invokes
   same-image configuration rollback. No OAuth or public writes happen here.
9. Owner may now authorize in the CRM. Verify account/location/review **GETs**,
   then confirm a single customer/location binding and explicit employee grants.
   Public reply/post verification needs exact content/merchant confirmation.

Use transport before callback protection: its fresh baseline intentionally still
requires original Nginx bytes. Finish the transport within its 15-minute lifetime.
There is no automatic authorization, binding, permission grant or provider write.

## Mandatory manual review object

Required flags, all actually reviewed and `true`:

- `independent_security_review_passed`
- `approved_dedicated_client_project`
- `existing_consent_screen_and_clients_preserved`
- `external_callback_logs_checked`
- `allow_exact_callback_logging_change`
- `allow_exact_six_environment_additions`

Other exact fields:

```json
{
  "stage": "GBP_ACTIVATION_MANUAL_REVIEW_APPROVED",
  "plan_sha256": "EXACT_REAL_PLAN_SHA256",
  "project_id": "t24-beauty-os-20260823",
  "callback": "https://t24-crm.com/api/v1/google-business/oauth/callback",
  "scope": "https://www.googleapis.com/auth/business.manage",
  "tool_sha256": {
    "core.py": "EXACT_REVIEWED_TOOL_SHA256",
    "preflight.py": "EXACT_REVIEWED_TOOL_SHA256",
    "activation.py": "EXACT_REVIEWED_TOOL_SHA256"
  },
  "business_writes": false,
  "provider_writes": false
}
```

Add the six listed flags to that object. Unknown review fields are rejected to
prevent accidentally embedding credentials in command output. Do not set flags
for unverified assertions or reuse a prior review after code/configuration drift.

## Command generation (local only)

```sh
python make_commands.py --phase preflight --out preflight-command.sh
python make_commands.py --phase diagnostics --out diagnostics-command.sh
python make_commands.py --phase transport-init --out transport-init-command.sh
python make_commands.py --phase transport-install --arguments ciphertext-arguments.json --out transport-install-command.sh
python make_commands.py --phase plan-nginx --out plan-nginx-command.sh
python make_commands.py --phase protect-callback --arguments reviewed-protect-arguments.json --out protect-command.sh
python make_commands.py --phase enable --arguments reviewed-enable-arguments.json --out enable-command.sh
python make_commands.py --phase rollback --arguments reviewed-enable-arguments.json --out rollback-command.sh
```

`ciphertext-arguments.json` contains only `transfer_id` and RSA `ciphertext`.
Protect arguments contain only `plan_sha256`, the public `review` object and
`review_sha256`. Enable/rollback add `logging_receipt_sha256`. Every command
embeds exact hash-checked tools; generating a command never executes it. Review
the command's digest before server execution. Keep the reviewed rollback command
available before enabling, including if the console loses the result.

## Recovery and credential boundary

The durable switch intent/candidate identity permits recovery after interruption.
Rollback validates the exact reviewed source/schema and known container identities;
it refuses unknown containers or altered credentials/runtime. It restores the
saved original environment on the same image, retains callback log protection,
and never restores databases, downgrades migrations, deletes Google rows/audits,
or globally revokes the shared Google project. Keep the Fernet key after OAuth:
losing/replacing it makes existing encrypted tokens unreadable. Retain protected
encrypted backups under the server's existing backup process; this tool does not
create an unapproved off-server secret copy.

The current application is environment-only. The host env file and protected
original Docker snapshots are root-only, but Docker administrators can inspect
runtime environment secrets. Secret-file-only runtime loading would require a
separate reviewed `_FILE` application change. No claim is made that Docker env
values are hidden from host administrators.

Tests use synthetic credentials, protected temporary files, real local RSA-OAEP
round trips and a fake Docker server. They never contact Google, Ali or production.
