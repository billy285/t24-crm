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

## 部署上线（推荐）

项目已经包含可直接上线的配置：
- 后端：Render（`render.yaml` 一键创建数据库 + API 服务）
- 前端：GitHub Pages（`.github/workflows/deploy-pages.yml` 自动发布）

### 1) 部署后端（Render）

1. 登录 Render 后点击 README 里的 **Deploy to Render** 按钮。
2. 选择当前 GitHub 仓库并确认创建。
3. Render 会按 `render.yaml` 自动创建：
   - Postgres 数据库 `billy285-t24-crm-db`
   - Python Web 服务 `billy285-t24-crm-backend`
4. 等待首次构建完成，打开以下地址确认后端健康检查：

   ```bash
   curl https://billy285-t24-crm-backend.onrender.com/health
   ```

### 默认登录账号（首次部署）

可以，默认情况下可直接用系统预置员工管理员账号登录：

- 前端登录页（直接访问）：https://billy285.github.io/t24-crm/
- 后端登录接口：`POST https://billy285-t24-crm-backend.onrender.com/api/v1/emp-auth/login`
- 账号：`admin@company.com`
- 密码：`admin123`

接口调用示例：

```bash
curl -X POST 'https://billy285-t24-crm-backend.onrender.com/api/v1/emp-auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@company.com","password":"admin123"}'
```

该账号由启动流程里的 `initialize_default_employee_admin()` 自动创建（受 `MGX_IGNORE_INIT_EMP_ADMIN` 控制）。

> 安全建议：首次登录后立即修改密码；生产环境不要长期保留默认密码。

### 2) 配置后端环境变量（Render Dashboard）

`render.yaml` 已内置关键变量，建议上线前重点确认：

- `FRONTEND_ORIGINS`：包含你最终前端域名（支持逗号分隔多个）
- `COOKIE_SECURE=true`
- `COOKIE_SAMESITE=None`（跨域登录需要）
- `ALLOW_INIT_ADMIN=false`（生产建议关闭）

如果你要使用自定义域名或 Vercel 域名，务必把新域名追加到 `FRONTEND_ORIGINS`。

### 3) 部署前端（GitHub Pages）

1. 打开 GitHub 仓库设置 → **Pages**。
2. Source 选择 **GitHub Actions**。
3. 推送到默认分支后，`deploy-pages.yml` 会自动构建并发布前端。
4. 发布成功后访问：
   - `https://<你的GitHub用户名>.github.io/t24-crm/`

### 4) 联调与验收清单

上线后建议按以下顺序验证：

1. 后端健康检查：`/health` 返回成功。
2. 前端页面可打开，且 API 请求目标为 Render 域名。
3. 登录、增删改查等核心流程可用。
4. 跨域与 Cookie 正常（浏览器无 CORS 报错）。
5. Render 日志无数据库连接异常。

### 5) 常见问题排查

- **前端请求报 CORS 错误**：检查 `FRONTEND_ORIGINS` 是否包含当前页面域名（精确到协议+域名）。
- **登录状态不生效**：确认 `COOKIE_SECURE=true` 且在 HTTPS 域名下访问。
- **首次部署较慢**：Render Free 计划冷启动可能需要更久，属于正常现象。
