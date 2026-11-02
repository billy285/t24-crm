# Reviewed additive media automation release

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
