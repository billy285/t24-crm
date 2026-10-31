# Google 单店试点与运营流程：无迁移补丁发布

本目录是独立新工具，不改此前已审发布器。生产基线固定源码 `c114242205af98c33a7c2ad435409e0c84ebd085`、前端 `33047aa593a2`、schema `acd7c9d0e136`、136 张表，绑定上一批 protected deployed receipt SHA `5639019ef95f88523eea7dc0548a74c0d7705871d7af834bb0b3b33d24ebd3bc`。本批源码、前端和统一冻结 SHA 在验收完成前保持 `None`，所有打包与发布操作提前拒绝，不能用零值占位。

## 允许的变更

应用仅 2 个后端运行文件、7 个前端源文件、2 个测试文件，以 `release.py` 的精确 allowlist 为准。运行包仅包含 2 个后端补丁和构建静态文件。所有其他应用文件必须与基线逐文件一致；模型、迁移、财务、关账、分润、权限及私人空间不属于本批。新增只读路由是 `GET /api/v1/google-business/bindings/{binding_id}/readiness`。

本批不运行 schema 迁移、初始化、seed、SQL 写入、政策开关、平台操作、任务/图片/租约/排期创建。当前已存在合法的图片政策 ON 和北方面食准备草稿，必须照实际基线保留，不适用“新表为空”或“policy OFF”条件。

## 只读基线与隔离准备

`preflight.py` 精确加载上一批受 root 0600 保护且 SHA 固定的工具，只复用已审 Docker、数据库只读指纹、元数据和日志解析原语。两次一致采样固定当前容器、镜像、完整 Env 指纹、挂载/网络配置、Google scheduler ON 与 cutoff `2026-10-30T19:42:04Z`、私有目录元数据、凭据文件元数据、136 表 schema/业务行/序列指纹及完整 Nginx 配置。业务原文、密钥和原图片不导出。完整 proof 仅写服务器 root 0600 文件，本地只拿摘要。

`prepare` 从精确当前镜像离线构建补丁，以生产数据库副本启动候选。副本 network none、无真实凭据、worker OFF。启动前后全部 136 表行、schema、SQL objects、pragma 和序列必须一致，包括已有非空政策和任务。实际 Python 3.10、Google/媒体/图片/计划路由同时按 OpenAPI 与 FastAPI route contexts 验证；隐藏图片 GET/HEAD 路由必须真实存在且不进入 OpenAPI。准备过程没有迁移容器，也不会写生产数据库。

## 切换与恢复

实际 prepared 回执 canonical SHA 独立审查后才生成 activate/recover。切换前精确复核基线，先创建新候选并持久写入、fsync 其 Docker ID，然后才停止旧容器。全程不删除生产容器、不还原数据库、不回写计数器。旧、新代码使用同一未变化的 schema。

Nginx 只更换一次静态 root；恢复 root 后完整文件和 `nginx -T` 必须与新鲜基线逐字相同。现有 OAuth callback 和图片 delivery 的禁止日志块不增删、不重建。切换后复用已审的 loopback 无能力标记 GET/HEAD 404 和有界日志扫描，检查受控日志通道没有暴露路径标记，不创建真实图片租约或访问 Google。

失败恢复先停止已持久绑定的候选，核对身份、schema、私有/凭据元数据、完整运行环境、源文件及 Nginx 边界，再恢复同 schema 的精确原容器。合法独立业务行留在共享数据库，不做快照回写；恢复时不要求行仍等于早先基线。未知容器、身份记录失败、私有/schema 漂移会提前拒绝，不猜测或删除孤儿候选。成功上线后的回退需要另行审查，不复用失败恢复入口。

## 固定包和执行顺序

1. 独立审查只读 preflight wrapper，根代理执行并保存 compact summary。
2. 根代理完成浏览器验收、提交 11 个应用文件并构建前端，写 `outputs/google-pilot-workflow-20261031/application-freeze.json`。要求 `source_sha/frontend_version/baseline_source_sha/schema_revision/database_migration:false/production_seed_rows:false/existing_image_policies_and_data_preserved:true/files`；`files` 是精确 11 文件的 SHA256 映射。
3. 固定 `SOURCE_SHA/FRONTEND/APPLICATION_FREEZE_SHA`；builder 比较完整 Git app inventory、本地源、前端源清单与 build 版本，确定性打包，不含数据库、环境文件、秘密、测试或私人素材。
4. 实际包与工具独立审查通过后，根代理提交 immutable carrier。生成器只取 raw HTTPS commit 的精确 4 个大小/SHA 绑定成员，拒绝代理与重定向。
5. 审查并执行 prepare，核对实际回执，再审查并执行 activate；最后核对 deployed 回执、公开版本与只读页面。

本地测试只用合成 SQLite、内存 Docker、临时 Git 和本地旧工具，不访问服务器、商家或平台。通过测试不等于已部署，也不等于已验证真实 Google 图文发布。试点真实内容仍需老板在发布前确认。
