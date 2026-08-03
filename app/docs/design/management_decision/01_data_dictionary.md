# 数据字典——新增旁路模型

本文件描述旁路新增表，不要求修改现有 `customers`、`payments`、`subscriptions`、`deals`、`customer_lifecycle_*`、`payroll_*` 等表。

实现状态：第 1–5 节已在本地完成模型与 migration；第 6–9 节仍是后续阶段设计，尚未创建数据库表。

## 1. `business_lines` 业务板块

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `code` | varchar(32) | UNIQUE, NOT NULL | `managed_service`、`restaurant_os`、`beauty_os`、`one_time_project` |
| `name` | varchar(80) | NOT NULL | 中文显示名称 |
| `is_recurring` | boolean | NOT NULL | 是否属于持续收费业务 |
| `is_active` | boolean | NOT NULL | 是否允许新建项目 |
| `created_at` | datetime | NOT NULL | 创建时间 |
| `updated_at` | datetime | NOT NULL | 更新时间 |

初始记录只能通过受控 migration/seed 创建，不允许用自由文本代替 `code`。

## 2. `product_catalog` 产品目录

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `business_line_id` | integer | FK, INDEX | 所属业务板块 |
| `code` | varchar(64) | UNIQUE, NOT NULL | 稳定产品代码 |
| `name` | varchar(160) | NOT NULL | 产品或套餐名称 |
| `billing_kind` | varchar(24) | NOT NULL | `recurring`、`one_time`、`usage` |
| `default_currency` | char(3) | NOT NULL | 默认货币，仅用于录入提示 |
| `is_active` | boolean | NOT NULL | 是否继续销售 |
| `effective_from` | date | NULL | 生效时间 |
| `effective_to` | date | NULL | 停售时间；不删除历史产品 |
| `created_at` / `updated_at` | datetime | NOT NULL | 审计时间 |

历史套餐改名时新增版本或调整显示名，不复用产品代码表达其他产品。

## 3. `customer_engagements` 客户产品项目

这是新增设计的核心。一位客户可以拥有多条产品项目。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 项目主键 |
| `customer_id` | integer | INDEX, NOT NULL | 关联现有客户 ID，不修改客户表 |
| `business_line_id` | integer | FK, INDEX | 业务板块 |
| `product_id` | integer | FK, INDEX | 产品目录 |
| `engagement_code` | varchar(64) | UNIQUE | 稳定项目编号 |
| `status` | varchar(24) | INDEX | 产品项目生命周期状态 |
| `owner_employee_id` | integer | INDEX, NULL | 当前负责人 |
| `sales_employee_id` | integer | INDEX, NULL | 成交销售 |
| `billing_cycle` | varchar(24) | NULL | `monthly`、`quarterly`、`annual`、`one_time` |
| `collection_method` | varchar(32) | NULL | `stripe_auto`、`bank_transfer`、`check`、`zelle`、`other` |
| `currency` | char(3) | NOT NULL | 项目结算币种 |
| `trial_started_at` | datetime | NULL | OS 试用开始 |
| `paid_started_at` | datetime | NULL | 有效付费生命周期起点 |
| `paused_at` | datetime | NULL | 暂停时间 |
| `stopped_at` | datetime | NULL | 正式停止时间 |
| `stop_reason_code` | varchar(48) | NULL | 停止原因代码 |
| `stop_note` | text | NULL | 详细说明 |
| `external_system` | varchar(32) | NULL | 外部 OS 类型 |
| `external_merchant_id` | varchar(128) | NULL | 外部商家 ID |
| `external_store_id` | varchar(128) | NULL | 外部租户/门店 ID |
| `created_at` / `updated_at` | datetime | NOT NULL | 审计时间 |

建议唯一约束：`(external_system, external_store_id, product_id)` 在外部字段非空时唯一。

## 4. `engagement_source_links` 旧数据关联

不向现有事实表增加外键，使用关联表建立可撤销映射。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `engagement_id` | integer | FK, INDEX | 客户产品项目 |
| `source_type` | varchar(32) | INDEX | `payment`、`subscription`、`deal`、`task`、`callback`、`expense` |
| `source_id` | integer | INDEX | 原表 ID |
| `link_role` | varchar(32) | NOT NULL | `start_source`、`billing`、`cost`、`service_activity` 等 |
| `confidence` | varchar(16) | NOT NULL | `exact`、`suggested`、`manual` |
| `linked_by_id` | varchar(64) | NULL | 操作者 |
| `linked_by_name` | varchar(160) | NULL | 操作者名称 |
| `linked_at` | datetime | NOT NULL | 关联时间 |
| `note` | text | NULL | 修正原因 |

唯一约束：`(source_type, source_id, link_role)`，防止同一事实被重复计入同一角色。

## 5. `engagement_lifecycle_events` 产品生命周期事件

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `engagement_id` | integer | FK, INDEX | 产品项目 |
| `event_type` | varchar(32) | INDEX | `trial_started`、`activated`、`paid_started`、`risk_opened`、`paused`、`stopped`、`reactivated` 等 |
| `effective_at` | datetime | INDEX, NOT NULL | 业务生效时间 |
| `reason_code` | varchar(48) | NULL | 原因代码 |
| `source_type` / `source_id` | varchar/integer | NULL | 事件来源 |
| `idempotency_key` | varchar(160) | UNIQUE, NULL | 外部同步防重复 |
| `actor_id` / `actor_name` | varchar | NULL | 操作者 |
| `note` | text | NULL | 说明 |
| `created_at` | datetime | NOT NULL | 写入时间 |

事件只追加，不覆盖历史事件。状态修正通过新增 `corrected` 事件和审计记录完成。

## 6. `revenue_recognition_schedules` 收入确认计划

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `engagement_id` | integer | FK, INDEX | 产品项目 |
| `source_payment_id` | integer | INDEX, NOT NULL | 现有收款 ID |
| `recognition_month` | char(7) | INDEX, NOT NULL | `YYYY-MM` |
| `revenue_class` | varchar(32) | INDEX | `service_revenue`、`os_subscription`、`ad_margin`、`one_time_project`、`pass_through_principal` |
| `currency` | char(3) | NOT NULL | 币种 |
| `amount` | numeric(18,2) | NOT NULL | 当月确认金额 |
| `status` | varchar(16) | NOT NULL | `draft`、`confirmed`、`reversed` |
| `calculation_version` | varchar(32) | NOT NULL | 公式版本 |
| `created_at` / `updated_at` | datetime | NOT NULL | 审计时间 |

唯一约束：`(source_payment_id, recognition_month, revenue_class, calculation_version)`。

`pass_through_principal` 只用于对账，不进入经营收入或 LTV。

## 7. `employee_role_targets` 岗位目标

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `employee_id` | integer | INDEX | 员工 |
| `role_type` | varchar(24) | INDEX | `sales`、`operations`、`admin` |
| `period_month` | char(7) | INDEX | 目标月份 |
| `metric_code` | varchar(64) | INDEX | 指标代码 |
| `target_value` | numeric(18,4) | NOT NULL | 目标值 |
| `weight` | numeric(6,4) | NULL | 观察权重；初期不接工资 |
| `approved_by_id` | integer | NULL | 审批人 |
| `created_at` / `updated_at` | datetime | NOT NULL | 审计时间 |

唯一约束：`(employee_id, role_type, period_month, metric_code)`。

## 8. `management_metric_snapshots` 管理指标快照

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `snapshot_date` | date | INDEX | 快照日期 |
| `scope_type` | varchar(24) | INDEX | `company`、`business_line`、`employee`、`engagement` |
| `scope_id` | varchar(128) | INDEX | 对象 ID |
| `metric_code` | varchar(64) | INDEX | 指标代码 |
| `currency` | char(3) | NULL | 金额指标必须有币种 |
| `value` | numeric(24,6) | NOT NULL | 指标值 |
| `sample_size` | integer | NULL | 样本量 |
| `quality_status` | varchar(16) | NOT NULL | `ready`、`immature`、`incomplete`、`warning` |
| `calculation_version` | varchar(32) | NOT NULL | 公式版本 |
| `calculated_at` | datetime | NOT NULL | 计算时间 |

同一快照不得将不同币种合并到一个金额指标。

## 9. `decision_signals` 决策信号

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | integer | PK | 主键 |
| `signal_type` | varchar(48) | INDEX | 招聘、投入、客户风险、数据质量等 |
| `scope_type` / `scope_id` | varchar | INDEX | 适用对象 |
| `severity` | varchar(16) | INDEX | `info`、`watch`、`action`、`critical` |
| `title` | varchar(200) | NOT NULL | 老板可读标题 |
| `explanation` | text | NOT NULL | 触发原因 |
| `evidence_json` | text/json | NOT NULL | 指标与阈值证据 |
| `rule_version` | varchar(32) | NOT NULL | 规则版本 |
| `status` | varchar(16) | INDEX | `open`、`acknowledged`、`resolved`、`dismissed` |
| `owner_employee_id` | integer | NULL | 跟进负责人 |
| `created_at` / `resolved_at` | datetime | NULL | 时间 |

决策信号只提供建议，不自动招聘、调薪、扣分、停止客户或修改财务数据。

## 10. 权限最低要求

| 数据 | admin | finance | sales manager | operations manager | employee |
|---|---|---|---|---|---|
| 商家与项目摘要 | 全部 | 全部 | 授权范围 | 授权范围 | 自己范围 |
| 收入及利润 | 全部 | 全部 | 仅批准摘要 | 仅批准摘要 | 默认不可见 |
| 工资和账户 | 审批 | 录入/发放 | 不可见 | 不可见 | 仅本人脱敏结果 |
| 团队记分卡 | 全部 | 无敏感工资 | 所属团队 | 所属团队 | 仅本人 |
| 决策信号 | 全部 | 财务相关 | 销售相关 | 运营相关 | 指派给本人 |
