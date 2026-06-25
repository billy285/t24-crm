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
```

Edit `.env.production`:

- Set `JWT_SECRET_KEY` to the generated value.
- Set `FRONTEND_ORIGINS` and `PYTHON_BACKEND_URL` to your HTTPS domain.
- Set `MASK_KEY` to another long random value.
- Do not keep `admin123` in production.

For a clean database only, temporarily enable first admin seeding:

```env
ENABLE_DEFAULT_EMPLOYEE_ADMIN=true
DEFAULT_ADMIN_EMAIL=your-admin@example.com
DEFAULT_ADMIN_PASSWORD=your-strong-password
```

After first successful login, set `ENABLE_DEFAULT_EMPLOYEE_ADMIN=false` and restart.

## 4. Start With Docker Compose

```bash
docker compose --env-file .env.production up -d --build
docker compose logs -f crm
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 5. Configure Nginx And HTTPS

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

## 6. Daily Database Backup

SQLite must be backed up. Install the backup script:

```bash
chmod +x deploy/backup-sqlite.sh
APP_DIR=/opt/t24-crm ./deploy/backup-sqlite.sh
```

Add a daily cron job:

```bash
crontab -e
```

```cron
15 3 * * * APP_DIR=/opt/t24-crm /opt/t24-crm/deploy/backup-sqlite.sh >> /opt/t24-crm/backups/backup.log 2>&1
```

## 7. Update The App Later

```bash
cd /opt/t24-crm
git pull
docker compose --env-file .env.production up -d --build
```

## Production Checklist

- HTTPS domain works.
- `JWT_SECRET_KEY` is not default.
- Admin password is strong.
- `ENABLE_DEFAULT_EMPLOYEE_ADMIN=false` after initial setup.
- Database backup runs daily.
- `/health` returns `{"status":"healthy"}`.
- Only ports `80`, `443`, and SSH are open.
