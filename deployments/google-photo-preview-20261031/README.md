# 私有 PNG 预览修复：纯静态发布

本目录独立新增，不修改此前发布工具。当前基线：应用源码 `5931e430e629fb633f846ebc068a8fc12d4b9a0a`、前端 `8cc54170ca26`、schema `acd7c9d0e136`、136 表、现有 CRM 容器 `987ff7a2f5dffcc72efdedc58e915c5efd75ef46c1b80266ede7c6f805aca153`。本批仅 2 个前端源文件和 1 个前端测试，以精确 allowlist 和统一冻结 SHA 为准。新源码/前端/冻结参数在根代理完成验收提交前为 `None`，打包和发布提前拒绝。

## 变更与保留范围

运行包只有 `static/` 构建资源。没有后端/API 代码、Docker 镜像、数据库、环境变量、密钥、私人素材或测试。本批不创建、停止、启动、替换或重启任何 CRM 容器，不执行迁移、政策开关、排期、图片租约、Google 请求或业务数据写入。

仅新建静态目录并替换 Nginx 中唯一的旧静态 root。反向复原 root 后，完整配置文件和 `nginx -T` 必须逐字等于只读基线；OAuth callback 和图片 delivery 隐私块、原 CSP 全部保持原字节。认证仍由原 API 执行；私有图不成为静态公开素材。

## 只读基线

`preflight.py` 固定上一批 protected deployed receipt 和 preflight 工具 SHA，复用已审的只读 Docker、136 表指纹、元数据、私有边界和 Nginx 解析工具。两次一致采样固定当前 runtime（ID/镜像/config/start/restart）、完整后端 inventory、Env 指纹、schema/全部行/pragma/序列指纹，以及现有素材、固定图、owner policy 和任务的合法行。所有表都按当前值保留，不要求为空或 policy OFF。

额外以 loopback HTTPS 读取 `/media-ops` 的响应头，不取页面正文、不发送 cookie 或凭据。必须是200且只有一份非空 CSP，记录其 SHA。完整 proof 仅保存在服务器 root 0600 文件；本地 compact summary 不含凭据、原始业务记录或原图。

## 准备、切换与失败恢复

`prepare` 只校验保护边界、解开严格 static-only 包、创建新静态目录并核对资源。它不运行候选应用，也不复制/迁移数据库；原容器和全部数据持续保持。实际 prepared 回执 canonical SHA 经独立审查后，才生成 activate/recover。

切换前重新核对 runtime、后端、全部136表、私有/凭据元数据、CSP、完整 Nginx；先持久写入原配置与切换身份并 fsync，再原子替换单 root 并 reload Nginx。上线检查公开版本、ready、CSP、runtime/API源码和全表行不变后才写 deployed 回执。

失败仅恢复已绑定原 Nginx root，不还原数据库、不修改序列、不操作容器。恢复保留期间产生的合法独立业务行。未知 Nginx 改动不会被覆盖；仅清理本工具已验证的 Nginx 临时文件。成功上线后的回退需要独立审查，失败恢复入口不会复用。

## 固定输入与顺序

1. 独立审查只读 preflight wrapper；根代理执行并保存实际 compact summary。
2. 根代理完成相同 CSP 下真实图片预览验收、提交精确3文件并构建。统一 `outputs/google-photo-preview-20261031/application-freeze.json` 必须包含 `source_sha/frontend_version/baseline_source_sha/schema_revision/files` 及 `static_only:true/backend_changes:false/database_migration:false/csp_changed:false/production_seed_rows:false/existing_image_policies_and_data_preserved:true`。`files` 是精确3文件 SHA256 映射。
3. 固定三个最终参数，builder 比较完整 Git app inventory、本地源、前端源清单与构建版本，只打包静态资源。后端和所有其他源文件保持精确基线。
4. 实际包与工具独立审查通过，根代理提交 immutable carrier。命令生成器只下载固定 HTTPS raw commit 的精确4个大小/SHA成员，拒绝代理、重定向、秘密或未追踪源。
5. prepare 实际回执独立审查后再审查/执行 activate，最后检查回执、公开版本和真实登录页面。

合成测试不会访问生产或供应商；测试通过、打包或部分检查都不等于完成线上验收。真实 Google 图文发布仍等待老板确认内容，本工具不创建公开图片租约。

## 已诊断的只读兼容重试

首次 prepare 在修改静态目录或 Nginx 前，被严格序列元数据检查拒绝。受审只读诊断确认全部136业务表行、schema、pragma和其他边界一致，只有 `monthly_deduction_rates` 的 SQLite 内部自增计数在合法重复 `INSERT OR IGNORE` 期间前进。新重试使用独立 scope `google-photo-preview-retry` 和全新服务器/静态目录，原失败四成员目录完整保留。

正常 prepare/activate 仅允许这一个已观察计数器单调前进：序列键集合、存在状态、pragma与其他所有计数器仍须逐字相同，全部136业务表行和schema仍必须完全一致。计数器回退、其他计数器变化、表行/结构变化都拒绝。工具不执行任何 SQL/计数器写入；失败恢复沿用已审的独立合法行保留规则。这项兼容不改变财务计算或数据。Manifest 与实际准备回执明确绑定该单一例外，原应用/前端/静态 payload 不变。
