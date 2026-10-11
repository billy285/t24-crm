# Private Stripe report release, 2026-10-12

Application source is frozen at `c1ae19b38fec8f62f044d4b0789f31662da12fbf`.
The live private backend baseline is `3c5b8c1d63b8f078e162e228750b508715699479`, image `sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886`.
The prior frontend version is `a9b66e086cb0`; the frozen new version is `913856b4d17b`.

This is an independent ten-to-eleven-table release. Historical four-to-ten finance and static-only navigation helpers are immutable and are not reused as migration authorization.
Only the private Stripe report cache table and owner index may be added. Stop private writers and make a protected SQLite backup before initialization; compare every existing private row, column, index and all 83 customer-system tables afterward. Keep both live databases, encrypted credentials, owner permissions and runtime environment in place. Never restore or delete a live database automatically.

`prepare_candidate.py` derives candidate and schema-compatible rollback images from the accepted actual private image. It preserves every unrelated backend/runtime byte, runs all 1173 private regressions on deployed Python 3.10 with no network or production mounts, and rehearses initialization, encryption and old API rollback against populated synthetic data. The rollback image contains only the reviewed appended cache model; the unmodified old image would reject the new table at startup.

`upgrade.py` requires a fresh authenticated server baseline, independently reviewed artifact hashes, candidate receipt, release lock and Nginx compare-and-swap. It never changes or restarts the CRM container, its environment or financial database. The private worker starts after schema/public verification. Bank and external AI flags remain disabled.

After publication, verify the real owner report, unauthorized/revoked sessions, account/mode, timezone, no-store and permission/partial warnings. A cache-miss report can update the connection updated_at timestamp; verify encrypted credential/account/mode/generation fields separately at that phase. Never report unavailable resources or incomplete coverage as confirmed zero.

The carrier contains code, offline tests and complete static assets only; no credentials or database contents. The deployment receipt distinguishes built, candidate-verified, deployed and live-owner-verified stages.
