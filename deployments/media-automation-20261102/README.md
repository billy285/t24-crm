# Reviewed additive media automation release

Final accepted state, 2026-11-02: application `c78b50a11e02`, UI
`569fa342f1c3`, carrier `904603fcf809`, deployed at-write controller
`8727edc4ae5e`, worker helper `c5acd2d20de6`. The current container uses the same
`f456f7aaca24` image with only the draft worker runtime flag added. Schema is
`h43fe567f803`, 165 tables. The stopped-writer baseline `2df9b0f4268f` proves
preservation of every current original table and sequence; no database was
restored. The original financial rules, permissions, private space and platform
execution flags remain unchanged.

The owner enabled two platform policies for pilot customer 38. The next target
is December 2026, preparation on November 24 at 09:00 America/Denver. No AI or
public publication was executed by this release. Desktop acceptance and the
390px mobile no-overflow check passed; owner visual evidence remains local.

Canonical evidence: [main release](main-deployed-envelope.json),
[worker preparation](worker-prepared-envelope.json),
[worker activation](worker-enabled-envelope.json), and the complete aggregate
[final audit](final-release-status.json). The successful worker action was a
separate **activate-only** process using its durable prepared receipt. The
`prepare_activate` convenience path is not accepted: its second `Enable`
construction triggers the retained-helper namespace guard. It was not fixed in
this release and must not be used for a new rollout.

The local recovery retry improvement is preserved separately as
[an unreleased patch](unreleased/recovery-idempotence.patch), with
[audit metadata](unreleased/recovery-idempotence.json). Its controller hash
`5e37434d1aea` was **not deployed**. The controller and test source files in this
directory match the actually deployed carrier. The instructions below retain
the preparation history; production activation used `at_write_release.py` and
its exact stopped-writer baseline instead of the earlier live-row snapshot.

This directory only contains release tooling and aggregate evidence. It does
not contain credentials, provider tokens or customer documents. None of the
generators executes a remote command.

1. Run the generated capture command on the authenticated, authorized Aliyun
   execution page. Save its aggregate JSON as `preflight.json`. The captured
   root-private proof pins two current read-only samples; historical receipts
   authenticate helpers but are never used as today's business row baseline.
2. Complete application tests and the reviewed frontend build, then commit the
   exact 23-file application change. Run `freeze.py --source-sha <commit>
   --preflight-summary .../preflight.json --dist <reviewed-dist>` locally.
3. Run `build_payload.py` with the explicit source, frontend version, freeze
   path/hash and preflight summary. The payload is exactly nine backend files
   plus allowed frontend static files. Freeze and package reject any unrelated
   application change, removed source, untracked frontend source or changed
   build.
4. Review and commit this directory and artifacts as an immutable carrier.
   `make_commands.py --carrier <commit> --preflight-summary .../preflight.json
   --out .../prepare-commands` produces the prepare command only. It downloads
   four exact committed public artifacts with no redirects; hashes and sizes
   are verified before installing root-private files.
5. Prepare builds an overlay on the exact current local image without network,
   copies the database into an isolated clone and performs only migration
   `g32ed456e792` → `h43fe567f803`. It proves all original 162 table definitions
   and business rows unchanged, the exact three new tables empty, and no
   sequence/pragma change. The candidate has no credentials/network and all
   workers off. Route, owner-only and default-off canaries run on actual server
   Python 3.10. Prepare never writes the production database.
6. Review the canonical prepared receipt. Regenerate commands with
   `--prepared-receipt <server-envelope-or-canonical-file>`. Activation verifies
   every boundary again, stops the old writer, applies the same transactional
   migration on the original database inode, starts one known candidate and
   changes only the Nginx public root. Existing hashed assets, CSP, credentials,
   environment, Google cutoff, Meta flags, finance, closing, commissions, ACLs
   and private-space boundaries remain fixed.
7. Recovery contains the known candidate, settles the recorded migration and
   resumes the old image. The additive tables and current rows remain. There
   is no database copy-back, downgrade, table drop or production row deletion.

The new draft worker remains **off** in this main release; no policies, AI
requests, public tasks or provider writes are seeded. Enabling draft preparation
is a separate, reviewed runtime-only action after this release is verified.
Real public publishing remains subject to the owner's separate confirmation.

After reviewing the main deployed receipt, `make_commands.py` additionally
accepts `--prepared-receipt <main-prepared>` and
`--worker-deployed-receipt <main-deployed>`. This produces only a worker prepare
command. It verifies the completed main release, exact runtime and three empty
tables. Once that worker prepared receipt is reviewed, add
`--worker-prepared-receipt <worker-prepared>` to generate separate activation and
recovery commands. Activation clones the same image and appends exactly
`T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=true` to the ordered Docker environment;
existing environment files, credentials, flags, source, schema and static root
remain fixed. It creates no policies and invokes no AI or publication. Only
afterward may the owner enable a particular merchant/platform in the UI after
reviewing its sources and generation notice. Worker recovery resumes the same
image without the new flag, preserving all current policies and business rows.

Focused tests: run the project Python with
`-m unittest discover -s deployments/media-automation-20261102 -p 'test_*.py' -v`.
