# 评论编辑上下文热修复：无迁移发布

此目录只包含发布准备工具，不代表已经上线。应用精确来源 `5a52cdcf8e9560fcf5ec6e2b27f264f6f0fe1087`，前端 `50347ba2c9da`；变更仅2个后端运行时文件、1个前端文件和1个隔离测试。原完整版本、财务/客户权限/私人空间以及旧发布工具不变。

基线固定为已核实部署 `17858808bd0ac0f825e8a51931bdf49cde6253f431a0ab7e8280b301fe3b9f37`、原源码6b47、前端b061、容器fc368、镜像925f、schema d9e4f6a7b803。此次不迁移、不新增表、不清空Google/AI数据、不调用真实Google或模型、不启用排期。

流程：

1. 先审查 `preflight.py` 和精确命令，再由root执行一次预检。完整129表行哈希、数据库inode/序列/pragma/完整schema、当前来源、环境哈希、私容器/凭据metadata、完整Nginx都保存到服务器root0600事实文件。stdout仅输出约2KB摘要、SHA和路径，不导出大表或凭据/私人内容。业务库仅SQLite URI mode=ro。
2. 本地 `build_payload.py --preflight-summary <实际摘要> --out artifacts` 验证精确Git app变更及所有未改源码，打包2个后端覆盖文件和编译static，不拷贝整个后端。镜像只以现有本地已核实镜像为FROM、COPY这2个文件，禁止拉取/网络构建。
3. 工具/manifest/payload经独立审查后，提交并push精确carrier。`make_commands.py --carrier <完整40位commit> --preflight-summary <实际摘要> --out <新目录>` 只生成prepare。每个成员须与carrier逐字匹配，carrier app树必须等于已审核source；远程按固定raw GitHub地址/commit/大小/SHA下载，禁代理与重定向。
4. prepare重新检查同一新鲜事实；使用隔离业务库副本、network=none、无生产env文件或secret mount、合成密钥、所有worker/Google/AI关闭的候选做实际Python3.10启动、精确新增review路由注册、所有旧路由保留及未改变schema/行/序列验证。保存不可覆盖prepared回执，等待独立审查。
5. 审查实际prepared后，生成器才允许生成activate/recover。activate在任何停机前创建并持久绑定候选CID，fsync目录，复查来源/环境/挂载/网络/所有metadata/行；随后保留原容器，启动候选，Nginx只替换唯一public root，回调日志脱敏和安全头完整hash保持。只读loopback `/ready`、`/app-version.json` 校验并再次完整复查后才写deployed回执。curl禁默认配置/代理，固定本机解析，不携带认证或查询。
6. 中断/失败用同prepared和carrier的recover：只停止已记录ID+镜像+角色的候选，核验schema/inode/metadata/旧来源安全后恢复原代码及静态root；保留停止候选，不删除原/候选，不恢复数据库、不撤销独立业务写入。恢复时仅允许同schema独立插入引起的sequence值变化，保留当前值；schema/PRAGMA/inode和其它边界仍严格，prepare/activate的sequence及全行检查不放宽。若保护边界漂移，则先停止已知候选，再拒绝不安全恢复，要求人工检查。创建后未能持久记录ID时原服务尚未被停止；不得按名称猜测删除或接管，需要人工检查未启动的孤立候选。

OOM比较仅对指定字段允许exact原None→候选False的Docker默认表示差异，或两边raw同值；True、数字0、缺失、反向False→None及其他变化拒绝。没有验证内核OOM行为。显式IPAM静态地址网络不支持，拒绝发布。

排期执行器仍保持OFF。之前为旧source6b47准备的排期plan不可用于此热修复后版本；需要以后另行按新deployed事实重新准备，并取得具体启用确认。
