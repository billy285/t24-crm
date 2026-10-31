# 第一阶段发布与独立验收边界

本文件为实施前的验收计划，不是完成或上线声明。独立验收不操作真实平台、不接触生产凭据、不发布真实内容。

## 生产保护基线

- 使用发布当时的新鲜生产事实，不沿用旧的 scheduler OFF 预检。当前调度已经启用；`T24_GBP_SCHEDULER_ENABLED` 与 `T24_GBP_SCHEDULER_ACTIVATION_FROM` 必须精确保留，不能重置起点、重复启用或造成新旧 worker 并行。
- 原 Google 连接密文、OAuth 状态、客户／门店绑定、逐店授权、生命周期、主要运营、公开操作记录、排期、AI 同意与草稿的旧列和值原样保留。不得借迁移自动授权、自动回填历史任务或重新发送旧操作。
- 财务计算、关账、分润、客户中心授权、私人空间、其他凭据、容器配置／环境／挂载／网络及 OAuth 回调日志保护保持不变。
- 隔离候选使用无网络、无生产凭据挂载、全部 worker 关闭的合成环境；正式候选保留原环境和调度起点。隔离关闭与线上启用不能混淆。
- 数据迁移只能执行经审核的新增字段／空表；逐表比较旧列投影、行数与散列、约束和索引。SQLite 自增计数不得倒退、清空或由工具恢复写回。
- 对旧任务的默认解释保持兼容：旧 STANDARD 草稿、审核记录和已排期内容无需无故重审。改变新增结构或素材引用则必须退回、修订及重新审核。
- 无准确公开内容授权，本轮验收只用假 provider 与真实只读页面；不得创建真实公开回复、帖子、活动、优惠或新排期。

## 必须覆盖的攻击／回归

1. 严格 JSON：未知键、嵌套未知键、错误 topic、额外平台、布尔／浮点伪装整数、非法日历日期／时间、开始结束倒置、过长字段、无偏移时间，以及未支持的 Google `scheduledTime`／重复活动／输出字段都拒绝。
2. URL／素材：CTA 和兑换链接允许正常 query，完整 URL 必须进入审批与指纹；仅允许明确公开 HTTPS，拒绝凭据、内部主机、数字 IP、控制符、反斜杠、fragment 及非 Web scheme。图片继续遵循原公开图片链接边界，不把图片禁 query 规则扩大到 CTA。禁止跨客户素材、owner-only 素材、未授权 materials 模块、图片和视频类型混淆；审核后改变素材引用或可见性必须拦截。服务端不抓取任意 URL。
3. 平台隔离：新增 Google 结构不能被 Facebook／Instagram 等草稿冒用；非 Google 内容不能调用 Google 公共写入，不能因平台字段变化继承已审核 Google 状态。
4. 版本与审核：CAS 拒绝旧 revision、同 UUID 不同结构、并发编辑；approve 快照包括精确结构与素材。直接改 DB 的测试 canary 不得绕过审核快照校验。
5. 排期：指纹包含新增结构、CTA／优惠链接、日期时间、素材；计划保存后任一字段漂移、撤权、暂停／停止、客户非合作、负责人改变均不能发送。旧无结构计划的指纹保持兼容。
6. 未知结果：超时、断连、取消、5xx 均不能盲重发；同 UUID 及新 UUID 不能让同一任务重复公开。恢复查询只有 GET；accepted／processing 与确实 LIVE 分开。
7. 不变性：财务、关账、分润、客户 ACL、私人空间合成 canary 在新建、编辑、提交、审核、发布、失败、排期和查询全过程不变。慢 provider 网络期间不持 SQLite 写锁。

## Google 字段核实依据

官方 LocalPost 资源：<https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts>

- EVENT 与 OFFER 都必须有 `event`；`event.schedule` 的时间区间须具备开始／结束日期和时间。
- OFFER 的 `offer` 只有优惠码、在线兑换链接、条款等相应字段；`callToAction` 对 OFFER 会被 Google 忽略，不能在审核预览中制造不存在的按钮。
- LocalPost media 只使用 `sourceUrl`；不能透传位置媒体上传的 `dataRef`。
- 第一阶段不接收原生 `scheduledTime`、`recurrenceInfo`、Google 输出 ID／状态等字段，沿用 CRM 的审核和调度边界。

具体字段名、默认值和测试结果以冻结 API 合同及后续独立验收回执为准。
