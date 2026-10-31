# 第一阶段内容规格与团队素材发布工具

此目录已按根代理确认固定应用源码 `6a7c0f7ee8d1b5eb9e24a5f0027cce24930d0667` 与已构建前端 `5af8aec0193c`。前端冻结清单 SHA 为 `3e4c03aebf856ac3bcb95a890b6c49a41b14b365424718fa1f95e17149b5538e`，后端最终冻结清单 SHA 为 `2c32158584c693043536cf1b13e16250c764f96ce35cb03774cbee7c765fc473`。源码与冻结清单固定不等于批准执行：仍须审查实际包、carrier 与脚本；实际 prepare 回执再次独立审查通过后才可 activate/recover。旧发布工具不修改；本工具不执行 Google、AI 或公开内容请求，不创建任务、排期或自动政策。

基线为 source `5a52cdcf8e9560fcf5ec6e2b27f264f6f0fe1087`、前端 `50347ba2c9da`、schema `d9e4f6a7b803`、实际 scheduler enabled 回执 `b7b1f50e0d5b306bc46ea415f4a160ab8cbeccfae879d6604a6d8607b9f83f29`。原 scheduler **ON** 与 `2026-10-30T19:42:04Z` cutoff 必须逐字保留。生产仅新增空表 `media_operation_publication_specs`，新 head 为 `eaf5a7b8c914`。不得初始化历史任务规格或修改旧 129 表的业务行、权限、财务、私人空间。

## 顺序与证据

1. 根代理通过已独立审查的 preflight capture，完整 129 表事实只留服务器 root 0600 文件；本地只接收 summary。`generate_preflight_command.py` 由根代理拥有，本工具不重复生成。
   本地实际 summary 对应服务器完整 proof SHA `af666ca67bd061a8eec573134acb3f8d575a14811458793ada0e2071ef2a5c2e`，服务器路径 `/opt/t24-crm/releases/media-publication-preflight-af666ca67bd0.json`。
2. builder 接收 summary，核对精确 Git app inventory、5 个后端运行文件、13 个前端冻结文件与 2 个测试文件；拒绝额外 app delta、未跟踪前端源文件、秘密和非法静态文件。包仅含 5 个运行文件与构建后的静态资源，绝不含生产环境变量、数据库、私文件或测试源码。
3. 固定完整 carrier SHA，生成 `prepare`。下载只允许固定 HTTPS raw commit，禁代理、重定向，逐个比大小/SHA；服务器只写全新 root 0700 发布目录，文件 0600。没有真实 preflight summary 时不能生成。
4. prepare 复制业务库，在网络 none、无凭据、所有 worker OFF 的副本上迁移和启动。核对唯一空表、原表 schema/index/行、pragma、sequence，实际 Python 3.10、精确 Media/Google 路由及离线无配置状态；不导出数据库或 129 表 proof。副本自己的迁移与启动前后 sequence 必须完全一致；从 preflight 到复制时只允许独立计数器向前，工具绝不写回计数器。
5. 独立核对实际 `MEDIA_PUBLICATION_PREPARED_OFFLINE_VERIFIED` 回执及 canonical SHA 后，生成 activate/recover。工具不把 prepare 视作上线验收。
6. activate 先创建并持久绑定精确停止候选 ID，再 stop 原 ON worker。只用无网、无密钥、worker OFF 的已绑定迁移容器升级生产 head，之后才允许启动同一新候选。保留全部现有 Env、cutoff、挂载、网络、现有 callback 日志脱敏与安全头；只改变已审阅静态 root。验收通过才写 deployed 回执。

## 失败恢复

候选 ID 未持久成功时，不停止原服务、不按名称猜测候选、不删除任何容器。已绑定候选先停止，再核对恢复边界。迁移仍未提交且数据库仍是精确旧 schema 时，可恢复原容器；一旦达到新 head，绝不再启动旧代码，恢复仅前移同一已绑定新镜像。迁移容器即使因输出/等待异常退出，只要已安全停止且新 schema 与副本审阅值完全一致，仍可按新 head 前移。恢复保留独立新增业务记录，不 restore 数据库、不删除历史、不回写 sequence。元数据/来源漂移时拒绝不安全启动，保留停止容器供根代理审查。

隔离 startup 临时容器沿用已审查原语的 `--rm`，停止后自动移除；生产原容器、新候选及持久记录的迁移容器不删除。原表的唯一预期行变更是 Alembic head 从 d9 更新到 eaf5，其他原业务行保持原样。

Docker OOM 仅接受指定 `OomKillDisable` 的 exact None→False 默认兼容，其余配置逐项一致；拒绝 True、数字 0、缺失和显式 IPAM。时间窗口复用已审查纳秒 Docker timestamp 解析器，180 秒验收，未声称验证内核 OOM 行为。

## 本地验证

三组作者测试只使用合成 SQLite、内存 Docker、临时 Git 仓库；运行 `test_release.py test_package.py test_commands.py`。`preflight.py` 和 `test_preflight.py` 由根与独立安全代理拥有，本工具不修改。工具的离线 startup/route 验收不是实际公开发帖测试；真正 Google 发帖交付未在本工具中测试。
