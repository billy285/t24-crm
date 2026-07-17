# RingCentral 接入准备清单

当前系统已完成第一阶段：销售在“每日 100 条拨打工作台”点击“一键拨打”后，会调起本机的 RingCentral 桌面应用，并在 CRM 留下发起拨打时间。通话结果仍由销售填写，系统不会在未授权的情况下声称已获取通话时长、接通结果或录音。

## 第一阶段使用要求

1. 每台销售电脑安装并登录 RingCentral Desktop。
2. 线索电话号码应使用 E.164 国际格式，例如 `+16265550100`。
3. 在电话销售中心打开“每日 100 条拨打工作台”，点击“一键拨打”。
4. RingCentral 应用完成通话后，回到 CRM 选择通话结果、填写备注和下次回访时间。

## 第二阶段自动同步前的准备

1. 准备正式域名，并将域名解析到 CRM 服务器。
2. 为域名启用 HTTPS。OAuth 回调地址必须是已登记的精确 HTTPS 地址。
3. 由 RingCentral 管理员创建 Server-side OAuth 应用，并登记回调地址：`https://你的域名/api/v1/ringcentral/oauth/callback`。
4. 在应用中申请最小必需权限：读取通话日志；需要同步录音时再追加读取录音权限。
5. 为每个销售员工确认 RingCentral 分机号，建立“CRM 员工 - RingCentral 分机”映射。
6. 仅在服务器的 `.env.production` 保存 `RINGCENTRAL_CLIENT_ID`、`RINGCENTRAL_CLIENT_SECRET` 和 `RINGCENTRAL_REDIRECT_URI`；不要在聊天、截图、前端页面或 Git 中暴露密钥。
7. 先用一个测试分机验证：拨打时间、接通状态、通话时长、去重同步；稳定后再全员启用。

## 后续实现范围

完成管理员授权后，系统将以 RingCentral 通话 ID 去重同步通话日志，并回填通话时长和结果；在取得录音读取权限、员工授权及当地录音合规确认后，再同步录音链接。嵌入式拨号器会放在这个阶段之后，避免未授权时出现无法拨打或数据不一致。
# RingCentral 电话销售连接

CRM 使用每位销售单独授权的 RingCentral OAuth 连接，不会把电话销售数据写入正式客户、成交或财务数据。

## 服务器环境变量

在生产服务器 `/opt/t24-crm/app/.env.production` 中添加以下变量，值只在服务器中保存，不要发送到聊天或提交 Git：

```env
RINGCENTRAL_CLIENT_ID=在开发者后台复制的 Client ID
RINGCENTRAL_CLIENT_SECRET=在开发者后台点击 Client Secret 后复制
RINGCENTRAL_REDIRECT_URI=https://t24-crm.com/api/ringcentral/callback
```

保存后执行 `docker compose --env-file .env.production up -d --build --force-recreate`，然后每位销售在“每日100条拨打工作台”点击“连接我的 RingCentral”完成各自账号授权。

## RingCentral 开发者后台

- 类型：REST API App
- OAuth：3-legged OAuth authorization code / Server-side web app
- Redirect URI：`https://t24-crm.com/api/ringcentral/callback`
- Refresh tokens：Yes
- App：Private
- 推荐 scopes：`ReadAccounts`、`RingOut`、`ReadCallLog`、`SubscriptionWebhook`

第一阶段保留 RingCentral 桌面应用拨号，CRM 会安全保存授权状态；自动同步通话时长、结果和录音将在后续 webhook 阶段开启。
