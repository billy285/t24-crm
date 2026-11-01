# 独立 Meta Publisher：凭据传输与启用

仅为独立 Publisher 应用增加运行配置。旧 Meta 只读应用、Google、数据库结构、所有 150 张现有表、财务、权限和私人空间保持原状。工具不调用 Graph API、不创建授权、不回复评论、不发布内容、不执行排期。

## 当前状态

独立 App `3037236509957803`、USER 配置 `2328579691236435`、八项权限及唯一回调已审核；功能 OFF 部署的版本、镜像、容器、发布工具及上线回执也已核实并固定。原 Meta 应用保持原状。新应用当前为 Development 模式，尚未在本阶段完成真实 OAuth 或任何发布。

150 表基线已从不可变 carrier 成功捕获，准确 SHA 为 `1bb4774655a7fd87664c591ef7463979cccdc26e362fa2c562c8ff668cc09522`，对应运行身份与 OFF 部署回执一致；捕获前保存的未审核 Facebook 草稿也已纳入基线。`baseline.py.BASELINE_SHA` 现已固定为该实际值。后续仍须先提交不可变 carrier，才能生成工具暂存、传输及启用预检命令；执行切换仍要求预检回执的准确哈希。

初始增加的配置固定为：`T24_META_OPS_ENABLED=true`、`T24_META_OPS_EXECUTION_ENABLED=false`、`T24_META_OPS_SCHEDULER_ENABLED=false`。其余八项为独立 App、密钥、USER 配置、Graph 版本、CRM 域名、准确八项权限和配置已审核标志。原环境变量顺序和值完整保留，追加总计 11 项。

## 实施顺序

1. 先完成代运营功能的 OFF 部署，核实真实 `deployed.json`、镜像、容器及发布工具哈希，再补充 `core.py` 的运行身份。
2. 确认新应用与两个旧应用不同，回调仅为 `https://t24-crm.com/api/v1/meta-operations/oauth/callback`；准确审核八项权限与 USER 配置。新 App Secret 不得复用旧只读 Secret，Token 加密密钥由服务器生成。
3. `make_commands.py --capture-out ... --carrier ...` 生成只读基线命令；只使用已提交且与功能版本 `app` 树相同的不可变 carrier。服务器比较两次稳定样本后保存全 150 表的计数/摘要及结构、源文件、环境、Google 排期、Nginx、静态资源与私人边界证据，不导出数据正文。
4. 核实基线回执，补充 `baseline.py.BASELINE_SHA`；在后续 carrier 中保持应用树不变。`make_commands.py --out ... --carrier ... --baseline-summary ...` 生成工具暂存、传输准备、启用预检与恢复命令，不包含启用命令。
5. 执行工具暂存与 `transport-prepare-command.sh`。服务器创建 15 分钟有效、一次性 RSA-OAEP SHA256 3072 位传输上下文。公钥可见；私钥仅存在受保护的服务器目录。
6. 只在可信 Meta 凭据页面使用 `encrypt-in-browser.js`。函数仅返回 384 字节密文的 Base64；禁止输出 DOM、剪贴板、明文 Secret 或未加密 JSON。将密文交给 `--receive-out ... --command-pins ... --transfer-id ... --ciphertext-file ...` 生成接收命令。接收端先持久占用传输，再解密和重新校验基线，写入独立 `/opt/t24-crm/secrets/meta-operations/runtime.env`，目录 0700、文件 0600。成功后删除临时 RSA 私钥。
7. 执行 `prepare-command.sh`，人工核实其脱敏 `META_OPERATIONS_ACTIVATION_PREPARED` 回执。再以 `--prepared-receipt ...` 重新生成命令；只有准确的服务器规范化回执哈希才能生成和执行 `activate-command.sh`。包含 `receipt_sha256` 的传输封装会先还原为服务器真正保存的规范字节。
8. 启用使用同一镜像，先持久保存候选容器 ID，再停止原容器、切换名称和启动候选。验收新 Provider 配置、执行及排期关闭、旧 Meta 读取可用、Google 原有排期及截止点不变、全 150 表无本工具写入。仅进行无真实凭据/状态的回调及无能力图片地址隐私探测。启用回执不能当作真实 OAuth、发帖、回复验收结果。

## 失败处理

发生超时或失败先读取既有受保护回执，不重复创建/覆盖凭据。接收已占用的密文不能重放；部分成功而回执写入失败时保留私有文件供人工核实，绝不覆盖。

启用失败只容纳持久记录的候选容器，再恢复准确原运行配置。所有数据库结构和独立新增业务、Meta 只读及 Ops 数据均保留，独立新凭据文件不删除。恢复关闭 Ops 运行配置，不撤销或删除任何远端授权。未持久记录的容器只报告需人工核实，不按名称猜测删除。成功启用后的恢复需要单独评审。

## 本地验证

测试仅使用合成凭据、临时文件、实际本地 RSA/WebCrypto 和合成 Docker；不连接服务器、Meta 或 Google。包括过期、跨上下文、重放、明文泄露、配置漂移、恢复保留新记录以及未复核回执不能切换等情况。
