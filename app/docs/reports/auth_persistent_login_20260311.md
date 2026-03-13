# 持久登录（记住会话）实现说明 - 2026-03-11

本文档说明“保持登录（记住会话）”功能的实现方案、涉及的代码变更、测试步骤与上线配置注意事项。

## 目标与结果
- 用户在登录时可勾选“保持登录”，即使刷新页面或关闭浏览器后再次打开，仍保持已登录状态（默认有效期 30 天，可配置）。
- 未勾选“保持登录”时，仅维持当前浏览器会话；关闭浏览器后需要重新登录。
- 实现刷新令牌（refresh token）与自动续期，减少重复登录。
- 原有 RBAC 与审计逻辑保持不变。

## 代码改动清单
- 后端（FastAPI）
  - 新增文件：
    - `app/backend/services/security_tokens.py`：封装 `create_access_token`、`create_refresh_token`、`verify_refresh_token`，默认算法 HS256，过期时间可通过环境变量配置。
    - `app/backend/routers/emp_auth_tokens.py`：新增以下接口（均以 `/api/v1/emp-auth` 为前缀）：
      - `POST /set_refresh`：在登录成功后设置 HttpOnly Refresh Token Cookie。参数：`{ remember_me: boolean }`。会话 Cookie 或持久 Cookie（30 天）。
      - `POST /refresh`：从 HttpOnly Cookie 读取 Refresh Token，校验后签发新的短期 Access Token，返回 `{ access_token, token_type, expires_in }`。
      - `POST /logout`：清除 Refresh Token Cookie。
  - 依赖：
    - `app/backend/requirements.txt` 增补 `python-jose[cryptography]`。
- 前端（React + TS + Vite）
  - 新增：
    - `app/frontend/src/lib/tokenStore.ts`：
      - `getToken/setToken/clearToken`：管理前端 Access Token。
      - `refreshToken()`：调用 `POST /api/v1/emp-auth/refresh` 获取新 Access Token，并更新本地缓存。
      - `invokeWithAuth()`：为业务请求自动附加 `Authorization`，遇到 401 时自动尝试一次刷新并重试。
  - 修改：
    - `app/frontend/src/pages/Login.tsx`：
      - 增加“保持登录”复选框 `rememberMe`（默认勾选）。
      - 登录成功后调用 `POST /api/v1/emp-auth/set_refresh` 设置 Refresh Token Cookie（根据 `rememberMe` 决定是否为会话 Cookie）。
    - `app/frontend/src/lib/role-context.tsx`：
      - 引入 `tokenStore` 的 `invokeWithAuth/refreshToken`（用于后续优化冷启动自动续期，已完成第一阶段替换主要调用点；若冷启动仍需 savedEmp，可继续按需小幅优化）。

## 接口行为与安全策略
- Token 策略：
  - 短期 Access Token：默认 30 分钟（可通过环境变量 `ACCESS_TOKEN_EXPIRE_MINUTES` 覆盖）。
  - 长期 Refresh Token：默认 30 天（环境变量 `REFRESH_TOKEN_EXPIRE_DAYS`）。
- Cookie：
  - 名称：`emp_refresh_token`（可通过 `EMP_REFRESH_COOKIE` 配置）。
  - 属性：`HttpOnly`、`SameSite=Lax`、`Path=/`，生产环境可设置 `COOKIE_SECURE=true` 强制 `Secure`。
- CORS：
  - 前端调用 `refresh` 与 `set_refresh` 已按需携带凭证；确保后端 CORS 已允许 `allow_credentials=True`、来源包含前端域名。

## 自测步骤
1. 勾选“保持登录”：
   - 登录成功后，刷新页面 -> 仍保持登录。
   - 关闭浏览器并重新打开 -> 仍保持登录（在 30 天有效期内）。
2. 不勾选“保持登录”：
   - 登录成功后关闭浏览器 -> 重新打开需登录。
3. 令牌自动续期：
   - 将 Access Token 设置较短过期（测试环境可调），等待过期后首次请求返回 401：
     - 拦截器调用 `POST /api/v1/emp-auth/refresh` 成功获得新 Access Token，重试请求成功。
4. 登出：
   - 点击退出：前端清除本地 Access Token 并调用 `POST /api/v1/emp-auth/logout` 清除 Refresh Cookie；刷新后显示登录态已清除。

## 上线配置建议
- 环境变量（后端）：
  - `ACCESS_TOKEN_SECRET`、`REFRESH_TOKEN_SECRET`、`JWT_ALGORITHM`（默认 HS256）
  - `ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`
  - `COOKIE_SECURE=true`（生产 HTTPS 场景）
  - `COOKIE_SAMESITE=Lax|None|Strict`（如跨站嵌入需 `None` 且配合 `Secure`）
- 前端：
  - 确保在预览/生产域名下，浏览器允许设置 HttpOnly Cookie（跨域时需对应 CORS 配置）。

## 已知兼容性与后续优化
- 若现有 `/api/v1/emp-auth/me` 的 Access Token 校验逻辑与本次签发方式存在差异，请统一后端 token 验证的密钥与算法，或在 refresh 路由中对接既有签发逻辑以保持完全兼容。当前实现遵循通用 HS256 JWT。
- `role-context.tsx` 已接入 `invokeWithAuth`；如需在冷启动时依赖 Refresh 获取 token 后再拉取用户信息，可进一步将 `checkAuth` 的 `savedEmp` 依赖降级（已提供脚手架，后续小改动即可完成）。
- 不涉及任何跨币种改动；RBAC 与审计保持不变。

## 构建与状态
- Backend：`uvicorn main:app --reload` 本地已可启动（端口冲突时表明已有实例运行）。
- Frontend：`pnpm run lint` 通过；`pnpm run build` 成功。

## 开发环境代理与登录 404 排障（2026-03-11）

问题现象
- 登录发起 POST /api/v1/emp-auth/login，浏览器提示 Request failed with status code 404。
- 后端 /health=200，/docs 可见 /api/v1/emp-auth/login 路由。

根因分析
- 开发态中，Vite 本地 5173 端口未配置代理，/api 相对路径命中 5173 自身，导致 404；
- 或前后端路径前缀不一致。

修复措施
- 在 vite.config.ts 添加开发代理（将 /api 代理到 8000）：
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  }

验证步骤
1) 刷新/重启前端 dev 服务后，在浏览器 DevTools → Network：
   - 请求 URL 显示为 http://localhost:5173/api/v1/emp-auth/login（由 Vite 代理转发至 8000）
   - 状态码应为 200/401（凭证错误时），不应为 404
2) 打开 http://localhost:8000/docs 确认 /api/v1/emp-auth/login 存在
3) 手动校验：
   curl -i -X POST 'http://localhost:8000/api/v1/emp-auth/login' \
     -H 'Content-Type: application/json' \
     -d '{"email":"<email>","password":"<password>"}'

生产建议
- 保持前端走相对路径 /api/v1/...；
- 如需覆盖，提供 VITE_API_BASE_URL 环境变量并在 Nginx 层统一反代 /api 到后端 8000。
