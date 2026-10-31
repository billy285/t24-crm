# 图片发布与跨平台编排的单批发布工具

仅新建本目录，不修改此前已审发布器。应用源码固定为 `c114242205af98c33a7c2ad435409e0c84ebd085`，前端版本 `33047aa593a2`，统一冻结清单 SHA `7baccdca74c1d4abb31dd0bc4c0afc4c9ed8de893d55d2f9b2686e1ff0cea7ef`。这些参数缺失或为零值时，打包、生成服务器命令及全部发布阶段仍提前拒绝。当前仅完成本地打包与工具验证，未执行本批生产 prepare、切换或公开图片投递。工具不执行平台请求、不创建任务、排期、公开图片租约或投递政策。

## 固定基线和最小变更

生产基线固定 source `6a7c0f7ee8d1b5eb9e24a5f0027cce24930d0667`、前端 `5af8aec0193c`、schema `eaf5a7b8c914`、130 张表，以及服务器 root 0600 的上一阶段 `deployed.json`（SHA `c4d66c9cd2ae3fc3cf18543138ce7f28c1764d31e28ed89668960ec8838cf35c`）。当前容器 `85037c222afa2d59be3a272083ffd12e8996524ceee6daf1378be8779126a3ef` 与镜像 `sha256:1363c9a6fb528bf7f97f4d92570a60116a29e1b2f7c34ff00825a4aa348e0874` 必须精确匹配。原 Google scheduler ON 与 cutoff `2026-10-30T19:42:04Z` 逐字保留，所有 Env、凭据挂载、网络与其他容器配置不变。

单一 SQLite 显式事务依次执行 `fbc6b8c9d025`、`acd7c9d0e136`，仅新增图片 4 表、计划 2 表和 6 个命名索引，完成后为 136 表。迁移不初始化任何行，不改旧 130 表的结构/索引/业务行，仅更新 Alembic head。图片投递政策表保持空，默认 OFF；旧任务不回填，不生成发布租约。图片与编排界面的使用必须继续通过现有客户、素材和 Google 操作权限，不扩展 ACL、财务、私人空间或分润。

## 证据和执行顺序

1. 根代理执行独立审查过的 `preflight-command.sh`，两次相同只读采样，捕获最新实际 130 表 baseline。全部表 fingerprint、原列名和 sequence 仅存服务器 root 0600 proof；本地只取 compact summary。固定旧应用/镜像、静态目录与完整 Nginx active 配置，拒绝 6 张新表或新投递 prefix 已存在。
2. 根代理完成整合源码、构建和浏览器验收后固定 `SOURCE_SHA`、`FRONTEND`、`APPLICATION_FREEZE_SHA`。统一清单位于 `outputs/media-workflow-20261031/application-freeze.json`，要求 `files` 为精确 32 个 app 文件的 SHA 映射，并包含 `source_sha/frontend_version/baseline_source_sha/old_schema_revision/schema_revision/additive_tables/production_seed_rows:false/image_delivery_policy_enabled:false`。新增应用文件必须进入 source commit，未追踪前端文件被拒绝。
3. builder 以 Git baseline 与 source 的完整 app inventory 比较，只允许 13 个 runtime、14 个前端 source 和 5 个测试文件；本地源码逐个核对。生成的 payload 仅含 13 个运行文件和构建静态资源，不含测试、数据库、环境变量、原图片或秘密。
4. 实际包独立审查后，由根代理提交 immutable carrier。`make_commands.py` 只从固定 raw HTTPS commit 下载精确大小/SHA 的工具与包，拒绝代理和重定向；服务器新建 root 0700 release 目录，文件 0600。
5. prepare 在网络 none、无凭据、worker OFF 的生产数据库副本中迁移、启动。原表及自己的序列/pragma 必须不变，6 表精确形状与全部空行被确认。实际 Python 3.10、Google/媒体/图片/计划路由同时用 OpenAPI 与 FastAPI route context 核对；图片投递 GET/HEAD 必须真实注册而不进入公开 OpenAPI。没有调用 Google、Meta 或 AI。
6. 实际 prepared receipt 的 canonical SHA 独立审查通过后，才生成 activate/recover。根代理执行切换，先持久化/fsync 停止候选与迁移容器 ID，再停原服务和迁移。验收通过后才有 deployed 回执。

## Nginx 最小修改

只允许更换静态 root 并增加 `location ^~ /api/v1/media-publication-images/delivery/`。新前缀复制当前严格核对的本地 API upstream/转发设置，加 `access_log off; error_log /dev/null crit;`，保留服务器安全头继承，不增加目录或文件代理。原 Google OAuth callback 和所有其他 locations 保持原字节。验收将新增块去除、root 复原，完整配置文件和 `nginx -T` 的 SHA 必须与 preflight 相同。应用的 Uvicorn 路径脱敏属于源码冻结与路由验收范围。切换后另外用不存在能力的随机标记执行 loopback HTTPS GET/HEAD，必须均为404且返回隐私/安全头；只检查Nginx有效日志路径的有限追加字节及该候选同时间窗stdout/stderr是否含标记，不输出原日志。其证明通过后才写日志保护成功。该检查不创建图片或租约，不调用Google，也不替代真实Google图片抓取与公开发帖验收。

## 失败与恢复

候选 ID 未持久成功，不停止原容器，也不按名字猜测/删除孤儿候选。绑定后先停止新候选，再核对凭据、私有目录元数据、来源、数据库与 Nginx 边界。两迁移同事务，失败只能回到完整旧 head 或完整新 head；中间 head 一律拒绝。未迁移可在精确旧 schema 恢复原容器；迁移完成后绝不启动旧代码，只能前移同一持久绑定候选。恢复保留之后的合法独立业务记录，不还原数据库、不删除容器、不回写序列。副本探针容器可 `--rm`，生产原/新候选及持久绑定迁移容器不删除。

## 本地验证与限制

作者测试仅合成 SQLite、内存 Docker、临时 Git 和 Nginx 配置，不访问生产或供应商。测试覆盖单事务第二步失败回滚、旧表/sequence 防漂移、前向恢复、来源与冻结清单、防秘密打包、不可变 carrier、Nginx token 路径日志保护及隐藏 GET/HEAD 路由检查。独立 review、实际包 review 和实际 prepared receipt review 是三个独立步骤；本地通过不等于上线，更不等于公开图片投递或 Google 帖子实测。
