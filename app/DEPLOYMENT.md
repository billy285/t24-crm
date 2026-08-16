# T24 CRM Production Deployment

This project can be deployed as one FastAPI service that also serves the built React frontend.

## Recommended Server

- Ubuntu 22.04 or 24.04
- 2 CPU / 4 GB RAM minimum for internal team use
- Domain such as `crm.example.com`
- Open firewall ports: `80`, `443`, and SSH only

## 1. Prepare The Server

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin nginx certbot python3-certbot-nginx sqlite3
sudo systemctl enable --now docker nginx
```

## 2. Upload The Project

```bash
sudo mkdir -p /opt/t24-crm
sudo chown -R "$USER":"$USER" /opt/t24-crm
cd /opt/t24-crm
git clone <your-repo-url> .
cd app
```

If you are moving existing local data, copy `backend/crm_dev.db` to:

```bash
mkdir -p data
cp backend/crm_dev.db data/crm_prod.db
```

## 3. Configure Production Environment

```bash
cp .env.production.example .env.production
openssl rand -hex 32
openssl rand -hex 32
```

Edit `.env.production`:

- Set `JWT_SECRET_KEY` to the generated value.
- Set `REFRESH_TOKEN_SECRET` to the second, independently generated value.
- Set `FRONTEND_ORIGINS` and `PYTHON_BACKEND_URL` to your HTTPS domain.
- Set `MASK_KEY` to another long random value.
- Do not keep `admin123` in production.
- Keep `DATABASE_SCHEMA_MODE=verify_only`. Production and Lambda startup never
  create or repair tables; a database that is not at the code's Alembic head,
  or is missing a required table or column, fails startup before serving traffic.

For a clean database only, temporarily enable first admin seeding:

```env
ENABLE_DEFAULT_EMPLOYEE_ADMIN=true
DEFAULT_ADMIN_EMAIL=your-admin@example.com
DEFAULT_ADMIN_PASSWORD=your-strong-password
```

After first successful login, set `ENABLE_DEFAULT_EMPLOYEE_ADMIN=false` and restart.

## 4. Build The Candidate, Back Up And Migrate

Before every release, stop application writes and take a verified database
backup. Build the candidate image first, then run Alembic with that exact image;
otherwise `docker compose run` may silently use the previous release image.
Apply migrations as an explicit deployment step, never from the web process:

```bash
docker compose --env-file .env.production build crm
docker compose --env-file .env.production run --rm --no-deps crm alembic -c alembic.ini upgrade head
```

Test the same command first against both a new empty database and a restored
production backup. Do not deploy a release until both databases reach the code
head and application startup succeeds in `verify_only` mode. The current
Phase 0 startup-policy change must therefore ship only with the separately
reviewed migration bridge that satisfies those rehearsals.

## 5. Start With Docker Compose

```bash
docker compose --env-file .env.production up -d --no-build crm
docker compose logs -f crm
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 6. Configure Nginx And HTTPS

```bash
sudo cp deploy/nginx/crm.conf /etc/nginx/sites-available/t24-crm
sudo sed -i 's/crm.example.com/your-domain.com/g' /etc/nginx/sites-available/t24-crm
sudo ln -sf /etc/nginx/sites-available/t24-crm /etc/nginx/sites-enabled/t24-crm
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com
```

Then open:

```text
https://your-domain.com
```

## 7. Daily Database Backup

SQLite must be backed up. Install the backup script:

```bash
chmod +x deploy/backup-sqlite.sh
APP_DIR=/opt/t24-crm/app ./deploy/backup-sqlite.sh
```

Add a daily cron job:

```bash
crontab -e
```

```cron
15 3 * * * APP_DIR=/opt/t24-crm/app /opt/t24-crm/app/deploy/backup-sqlite.sh >> /opt/t24-crm/app/backups/backup.log 2>&1
```

Backups are only trustworthy after a restore test. Run the non-destructive
verification after installation and at least weekly:

```bash
chmod +x deploy/verify-backup-restore.sh
APP_DIR=/opt/t24-crm/app ./deploy/verify-backup-restore.sh
```

The verification checks the SHA-256 file, gzip archive, SQLite integrity and
required business tables inside a temporary directory. It never overwrites the
production database.

Keep a second encrypted copy outside this server (for example OSS with versioning
and lifecycle retention). A backup stored only on the application server does
not protect against disk loss, accidental server deletion or account compromise.

## 8. Update The App Later

The legacy `deploy/release-company-roadmap.sh` script is retired and exits
before doing any work. It predates the migration-only startup policy and must
not be used for Phase 0 or later releases.

```bash
cd /opt/t24-crm
git pull
cd app
docker compose --env-file .env.production build crm
docker compose --env-file .env.production run --rm --no-deps crm alembic -c alembic.ini upgrade head
docker compose --env-file .env.production up -d --no-build crm
```

## 9. Roll Back A Failed Candidate

Do not use `alembic downgrade` as a production rollback. Stop the candidate
container and reactivate the previously verified image or checkout. If the
release migration wrote to the database, restore the verified pre-release
backup before reopening traffic. A production database stamped at
`f3a7c9d2e611` advances to `f5d8a2c7b901` by adding six explicitly validated
lookup indexes. The migration performs no table rebuild and no business-data
update. It must first pass on a restored production backup with unchanged table
counts, business-data fingerprint and uniqueness checks. Rollback remains the
previous verified image plus the verified pre-release backup; never use
`alembic downgrade`.

## Production Checklist

- HTTPS domain works.
- `JWT_SECRET_KEY` is not default.
- `REFRESH_TOKEN_SECRET` is present, strong and different from `JWT_SECRET_KEY`.
- Admin password is strong.
- `ENABLE_DEFAULT_EMPLOYEE_ADMIN=false` after initial setup.
- Database backup runs daily.
- Latest backup passes `verify-backup-restore.sh` every week.
- An encrypted, versioned backup copy exists outside the application server.
- `.env.production` keeps `DATABASE_SCHEMA_MODE=verify_only`.
- Alembic upgrade and `verify_only` startup both pass on a fresh database and a
  restored production backup before rollout.
- `/health` returns `{"status":"healthy"}`.
- Only ports `80`, `443`, and SSH are open.
