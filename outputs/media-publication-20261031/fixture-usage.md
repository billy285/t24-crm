# 多平台代运营第一阶段：纯合成界面验收

此脚本尚未启动。只绑定 `127.0.0.1:8930`，读取本地 `app/frontend/dist`，需要根代理先构建本次前端。

```sh
/Users/billyli/Documents/Codex/2026-10-07/sites-plugin-sites-openai-curated-remote-3/work/experience-python/bin/python outputs/media-publication-20261031/qa-server.py
```

- 入口：`http://127.0.0.1:8930/media-ops`
- 实际窄屏 iframe：`http://127.0.0.1:8930/__media__/mobile?width=320`（可用 390、430）
- 状态与本地写记录：`http://127.0.0.1:8930/__media__/status`
- 本地账号 `owner` / `ops11` / `ops12`（只读）/ `ops13`（未授权）/ `owner2`；密码由启动输出读取，来源是旧合成 fixture 固定值。
- 账号 token 全是本地合成生成，不读真实 token；临时 SQLite 和上传目录位于新建临时目录，退出销毁。没有生产 lifespan、DB、凭据或真实供应商请求。
- GoogleClient 全部替换为本地 FakeGoogle；AI 回复也用固定合成结果。OAuth/connection 写入 409，其他原有业务写由 base fixture 409 拒绝。只有本次 Media Ops / Google 管理任务 / 客户团队素材用于合成验收。
- 上传只进入临时素材目录。初始私有素材没有公开 URL。没有远程预览图，不能用本地合成“发布成功”冒充真实平台验收。

## 已准备状态

1. 待准备 / 待审核 / 待发布 / 需处理 / 已完成 / 只读任务均可展示。
2. `合成优惠 · 完整条款与兑换链接` 已审核，包含优惠起止、WEEKEND20、带正常 query 的兑换链接、完整条款。
3. `合成活动 · 完整日期与预约按钮` 已审核，包含活动起止、预约 CTA 与带 query 的链接。
4. 旧 Google 普通图文 `publication=null`，按普通图文展示。
5. `合成 Google 草稿 · 尚未审核` 关联私有素材，不能假装具有 Google 可用公开图片。
6. ops11 客户资料 + 交付 + 素材读写；ops12 只读；ops13 未邀请；另一老板商家不应进入当前老板视图。

## 根代理建议验收

- 桌面与 320 / 390 / 430：三入口无横向溢出；主要操作有清晰按钮；长优惠条款、长 CTA URL 换行。
- 新任务切换 EVENT / OFFER / STANDARD，校验活动起止、跨时区预览和 OFFER 不提供 CTA。
- 新任务从 Google 切到 FB/IG，明确人工模式；保存请求不得携带 publication。
- 优惠/活动的审核详情、Google 待发布、发布确认、排期确认均可看到完整结构化字段。操作历史仅展示保留期内真实快照。
- 切换客户或工作区时拦截未保存修改；提交或结果未知时禁止切换。
- 团队素材：加载/失败/空态明确；只读不出现保存入口，未授权不出现旧素材；私有上传说明不代表可自动发布。

`python3 -m py_compile` 已通过；真实 router/contract 的合成启动检查将在后端契约完成后执行，不与生产会话连接。
