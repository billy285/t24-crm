# 独立私人工作空间

入口为 `/private-workspace`，支持桌面和手机。指定老板账号可从个人菜单或手机「更多」进入。其他管理员、销售账号和未指定的超级管理员均不能访问；修改 CRM 的可配置权限不能开放私人空间。

## 与客户财务的边界

- 私人事项、授权凭据、来源快照和同步记录使用独立数据库及独立 SQLAlchemy metadata，不进入客户系统的数据库或迁移。
- CRM 数据库仅用于读取员工身份、当前角色与在职状态。后台同步进程使用数据库只读连接。
- 银行邮件、Stripe 资金动态及广告费用不写入 CRM 收款、退款、利润或投流月结，也不参与任何客户财务计算。
- Stripe 收款、退款、争议和提现保留各自平台状态；提现不是收入，平台显示已提现不代表银行已到账。余额按币种分开展示，不与银行邮件重复相加。
- Bank of America 第一阶段接入其发送至 Gmail 的通知邮件，始终标记待核实，不冒充完整银行流水或确认到账。
- 页面仅提供私人事项管理和只读来源同步；不发送邮件、修改广告、发起退款、转账或提现。提醒目前在私人空间内查看，不承诺手机系统推送。

## 服务器配置

所有秘密仅配置在服务端环境中，不放入前端、Git 或浏览器存储。

| 配置 | 用途 |
| --- | --- |
| `PRIVATE_WORKSPACE_OWNER_IDS` | 指定本人员工 ID，例如 `123`。必须是当前在职或试用期的超级管理员；为空或格式错误时全部拒绝。不要直接复制其他环境的 ID。 |
| `PRIVATE_WORKSPACE_DATABASE_URL` | 独立数据库；默认 `sqlite+aiosqlite:///./private-data/workspace.db`，也支持独立 PostgreSQL 数据库。禁止复用 CRM 数据库。 |
| `PRIVATE_WORKSPACE_ENCRYPTION_KEY` | 新生成的高熵秘密，至少 32 字符；独立于 CRM 密钥，备份时与数据库分开保存。变更后原授权须重新连接。 |
| `PRIVATE_WORKSPACE_PUBLIC_URL` | 固定 HTTPS 站点 origin，例如 `https://t24-crm.com`，无路径、查询或片段。 |
| `GOOGLE_WORKSPACE_CLIENT_ID` / `GOOGLE_WORKSPACE_CLIENT_SECRET` | Google Web OAuth 应用。兼容 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`，建议使用本模块专属应用。 |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Google Ads 开发者令牌。 |
| `PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID` | 本人的目标广告账户，10 位数字或带横线；兼容 `GOOGLE_ADS_CUSTOMER_ID`。 |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | 经 MCC 访问时的经理账户 ID，可选。 |
| `PRIVATE_WORKSPACE_STRIPE_KEY` | Stripe restricted key，`rk_live_` 或 `rk_test_`，只授予 Balance、Charges、Refunds、Disputes、Payouts 的读取权限。拒绝 `sk_` 全权限密钥；本模块也不包含任何资金写操作。 |

SQLite 使用专属目录，目录权限须为 0700、文件 0600；模块会安全创建新目录，但不会修改已有共享目录的权限。生产环境须同时保护该目录中的 journal/WAL、备份及密钥。PostgreSQL 应使用只可访问该独立数据库的专用账户；数据库名称和连接目标必须与 CRM 不同。

Google OAuth 回调地址分别登记为：

```
https://t24-crm.com/api/v1/private-workspace/oauth/gmail/callback
https://t24-crm.com/api/v1/private-workspace/oauth/bofa/callback
https://t24-crm.com/api/v1/private-workspace/oauth/google_ads/callback
```

Gmail 和银行邮件使用 `gmail.readonly`，由本人逐次授权。Google Ads 的官方 OAuth scope 是 `adwords`，本模块只允许两条固定查询，不调用广告修改接口；部署前按 Google 要求完成所需 API 启用、测试用户或应用审核配置。授权 state 十分钟过期、来源与本人绑定且只能使用一次。部署时须使反向代理和 API 访问日志仅记录路径，尤其 OAuth 回调不得记录查询参数、请求体或授权头，避免短期授权码进入日志。

配置完成后，以指定本人账号进入「接入管理」，逐个连接并同步。没有配置的来源显示待配置，不生成样例资金或伪造连接成功。

## 同步范围与运行

同步是有范围的近期快照，不是完整历史账本：Gmail 只取近 60 天重要或星标邮件，最多 40 条；银行通知最多 40 条；广告监测为近 30 天最多 100 个广告系列；Stripe 每类记录最多 100 条。界面保留覆盖范围及截断状态，列表不能用于推断完整历史总额。Stripe 可用/待结算余额采用平台当前余额快照并按币种显示。

从 `app/backend` 使用部署环境的 Python 启动独立进程：

```
python -m services.private_workspace_worker
```

该进程不会启动 CRM 的初始化、财务定时任务或业务迁移。它每分钟检查已连接来源，默认每 15 分钟同步；私人偏好 API 可设置 5 分钟至 24 小时。每次复核本人当前访问资格，单来源超时隔离，断开连接会清除加密凭据并阻止旧同步结果写回。断开保留之前的私人记录，来源连接状态会明确显示。

应由现有进程管理工具单独管理 worker，并保持 API 与 worker 的同一部署环境、独立数据库路径和加密密钥。该文档只提供部署配置，不代表真实账号已接入或生产已上线。

## 后续扩展平台

在 `services/private_workspace_providers.py` 的来源 registry 中增加定义与只读适配器，再同步更新来源 schema、固定域名及请求 allowlist、导航和测试。每个来源使用稳定外部 ID 防重复，凭据保持服务端加密，保留原始平台状态和证据来源。接入新的写操作、银行原生连接或系统推送时需另行定义授权与审核流程。
