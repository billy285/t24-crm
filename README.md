# T24 CRM

Frontend:
- GitHub Pages: [https://billy285.github.io/t24-crm/](https://billy285.github.io/t24-crm/)

Backend:
- Render blueprint is defined in [`render.yaml`](./render.yaml)
- One-click deploy: [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/billy285/t24-crm)

Notes:
- The backend blueprint provisions a Render Postgres database and a Python web service together.
- On first startup, the backend will auto-create the default employee admin account.
- After the backend is live, GitHub Pages will call `https://billy285-t24-crm-backend.onrender.com`.
