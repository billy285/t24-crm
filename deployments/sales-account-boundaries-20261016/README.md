# Sales account boundaries: backend-only release

The package overlays exactly three Sales Center routers on the pinned, currently deployed CRM image. It tightens RingCentral call-status scope, serializes legacy sales-profile writes with transfers, and limits sales handoff/payment-confirmation capabilities. The source SHA and every payload member are frozen before publishing an immutable carrier.

No frontend, nginx, environment, migration, customer permission, commission, company calculation, closing-rule or private-space files are shipped. The previous frozen dossier helper is hash-pinned and reused only for read-only boundary checks, SQLite backups to isolated copies, offline startup, and Docker/runtime utilities. Its migration and public-file publishing operations are never called.

Preparation verifies the exact live CRM image, container and configuration; unchanged schema revision, private services, nginx and full public-file fingerprint; and the three baseline source files. The candidate is built with no network from the exact local image and three explicit `COPY` instructions. It starts with no network on an isolated database copy; every existing row, schema object and protected backend file must remain unchanged apart from the approved router replacements.

Activation requires independent review of the protected preparation receipt. It stops only the pinned CRM and verifies the stopped state before taking a backup, retains that container, then starts the reviewed candidate with the same environment, command, host configuration, mounts and networks. All boundaries and protected files are checked again. Existing data and schema must remain unchanged during the swap.

Recovery stops only an owned candidate and resumes the retained original CRM against the same verified schema. It never restores a database snapshot, restarts private services, or changes static files or nginx. Unrecognized containers, changed configurations and schema drift fail closed. A successful deployment cannot be automatically undone by the recovery command.

Run the focused guard tests, build from the exact source commit, save the payload and manifest in a separate carrier commit, and use `make_commands.py` to generate hash-pinned acquisition/preparation commands. After inspecting the exact prepared receipt, generate activation and recovery commands. Server checkout files are never reset or edited.
