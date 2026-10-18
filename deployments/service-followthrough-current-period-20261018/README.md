# Current-period renewal observation patch

Backend-only forward patch: service_follow_through.py plus its exact focused test. Frontend version d1dffbe546bf, static root, nginx, schema c0f4a8d6e123 and all104 existing tables remain unchanged. No migration, catalog seeds, financial calculation, close rule, commission, customer invitation or private workspace change. Source frozen at aa3461c2eed92269ebdf7b55ce182ec04619b04b. Fresh authenticated104table/340backend/runtime/private/static/schema proof is pinned at e237c5abcc101537c6c115efb7529bdd66c40d7c36df225629a361257d92f72c. Localreleaseguards pass60tests; activation still requires independent prepared-receipt review.

Preparation builds with no network on the exact deployed image, retains full backend inventory and starts an isolated database copy. Every existing table row/schema/index/trigger/view and static/nginx/runtime/private boundary must remain unchanged. Activation requires separately reviewed prepare receipt. Recovery only restarts/recreates the approved new candidate code; it never starts the old application or restores database backups.

Fresh read-only preflight proof and legacy private-boundary proof remain separately hash-pinned. Receipt installation writes only root0600 safe proof JSON with exact hash, no credentials; all commands are generated only and are never automatically executed.
