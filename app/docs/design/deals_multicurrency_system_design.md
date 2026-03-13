# Deals 模块多币种支持 — 系统设计文档

作者：Bob（架构师）  
日期：2026-03-11（Los Angeles）  
范围：仅设计与落地清单，不含编码

## 0. 目标与设计原则

- 目标：为 Deals 模块提供完整的多币种支持，覆盖数据模型、汇率、聚合计算与展示口径，确保“默认分币种展示与求和、不做隐式跨币合计”。当且仅当显式传入 base_currency 时，按历史汇率换算至基准币，并在接口与前端明确标注单位。
- 关键原则：
  - 金额以“最小货币单位”（minor unit）存储为整数，避免浮点误差（例如 USD: cents，CNY: 分，JPY: 不含小数）。
  - 汇率按“日”粒度（as_of_date）管理，跨日区间按日换算后再聚合。
  - 与“月度扣点比例”联动：先按月分桶，套用每月扣点，再做币种内汇总；如需转基准币，统一采用“先扣点后换算”的口径。
  - 保持现有“跨币种分离统计”与“保持登录（30天免登）”方案不受影响。
  - 权限与审计沿用现有 RBAC/操作日志规范。

---

## 1) 数据模型与存储

### 1.1 Deals 表（如不存在则新增/如存在需迁移）
- 表名：deals
- 字段（建议）：
  - id: BIGSERIAL/UUID PK
  - amount_minor: BIGINT NOT NULL — 以最小货币单位存储（如 USD 12.34 存为 1234）
  - currency_code: CHAR(3) NOT NULL — ISO 4217（如“USD”“CNY”“JPY”）
  - currency_exponent: SMALLINT NOT NULL — 货币小数位（USD=2，CNY=2，JPY=0），便于格式化/校验
  - deal_date: TIMESTAMPTZ NOT NULL — 成交时间（用于映射到日/月桶）
  - counterparty: TEXT — 相对方（客户/供应商/渠道）
  - customer_id: BIGINT NULL — 关联客户（如有）
  - sales_rep_id: BIGINT NULL — 关联销售（RBAC）
  - status: VARCHAR(32) NOT NULL — 例如 draft|won|lost|cancelled
  - deal_type: VARCHAR(32) NULL — 例如 new|renewal|upsell（可选）
  - notes: TEXT NULL — 备注
  - created_at: TIMESTAMPTZ DEFAULT now()
  - updated_at: TIMESTAMPTZ DEFAULT now()
- 冗余可选（仅当需要统一基准快速统计时）：
  - amount_in_base_minor: BIGINT NULL — 冗余为基准币的最小单位数值
  - base_currency_code: CHAR(3) NULL
  - fx_rate_used: NUMERIC(18,8) NULL — 记录入账时采用的基准汇率（仅在业务需要“入账即固定”的场景）
- 说明：
  - 默认不启用冗余列；基准币口径走运行时换算，避免历史口径不一致引发回溯矛盾。
  - 对于多币统计性能优化，可后续评估按天/按月物化视图或增量聚合表。

### 1.2 历史汇率表 fx_rates
- 表名：fx_rates
- 字段：
  - id: BIGSERIAL PK
  - base_currency: CHAR(3) NOT NULL — 基准币（例如 USD）
  - quote_currency: CHAR(3) NOT NULL — 报价币（例如 CNY）
  - as_of_date: DATE NOT NULL — 汇率适用日期（UTC 基准或系统统一时区）
  - rate: NUMERIC(18,8) NOT NULL — 表示 1 base_currency = rate quote_currency
  - source: VARCHAR(64) NULL — 数据来源（可选）
  - created_at: TIMESTAMPTZ DEFAULT now()
- 约束与索引：
  - UNIQUE(base_currency, quote_currency, as_of_date)
  - 索引：idx_fx_rates_bq_date(base_currency, quote_currency, as_of_date)

### 1.3 货币元数据（可选表/常量）
- currency_meta（或配置常量）：currency_code, exponent, symbol, name
- 用于校验与格式化（前端主要使用 Intl.NumberFormat；后端用于校验与 minor 单位转换）

### 1.4 与月度扣点比例的关系
- monthly_deduction_rates（已存在/已新增）：
  - year_month: DATE (yyyy-mm-01) UNIQUE
  - rate: DECIMAL(5,4) — 小数表示（0.15=15%）
- 使用规则：按 month(deal_date) 映射当月扣点比例；跨月统计时按各月不同扣点比例分别计算后再汇总。

---

## 2) 聚合与统计口径

### 2.1 默认口径（不跨币）
- 默认返回“分币种结构”，即同一响应内不同币种分别列出（不可相加）。
- 示例：
  ```
  {
    "range": {"start":"2026-01-01","end":"2026-03-31"},
    "group_by":"month",
    "results":[
      {"month":"2026-01","currency":"USD","revenue_gross_minor": 123456, "deduction_rate":0.15, "deduction_minor":18518, "cost_minor":90000, "profit_minor":14938},
      {"month":"2026-01","currency":"CNY","revenue_gross_minor": 345600, "deduction_rate":0.15, "deduction_minor":51840, "cost_minor":200000, "profit_minor":93760},
      ...
    ],
    "base_currency": null,
    "include_fx": false,
    "warnings":[]
  }
  ```

### 2.2 显式基准币口径（需要 base_currency）
- 请求包含 base_currency=USD|CNY|... 且 include_fx=true 时：
  - 拆分为“日”桶：对每一天内同币种求和，先按“当月扣点比例”计算净额，再以该日汇率换算到基准币，最后跨日聚合。
  - 跨月时：仍按各自月份扣点比例；扣点先应用再换算（避免扣点重复计算或因换算改变扣点口径）。
- 缺失汇率策略：
  - “向后填充”（backward fill）：从 as_of_date 向前查找最近可用汇率（例如最近 7 天内）；超过阈值仍缺失则返回 200 + warnings 列表或 422 错误（具体策略可通过 query 参数 strict_fx=true 控制）。
- 舍入与整分：
  - 扣点、换算结果均在“最小单位”层面四舍五入（银行家舍入可选，但建议普通四舍五入），确保整数。

### 2.3 扣点与利润计算公式（币种内）
- 令 revenue_gross_minor 为毛流水（最小单位），monthly_rate 为该月扣点比例（0~1），cost_minor 为成本（最小单位）：
  - deduction_minor = round(revenue_gross_minor * monthly_rate)
  - profit_minor = revenue_gross_minor - deduction_minor - cost_minor
- 跨币到基准：
  - 先算 profit_minor，再以当日 fx 将 profit 转换为 base 的 minor 单位（或先转 revenue_gross 与 cost，再扣点，二者只要全局统一即可；本方案选“先扣点后换算”）。

---

## 3) 后端接口变更

### 3.1 CRUD 与列表（保持风格与现有路由一致）
- 路由前缀：/api/v1/deals
- 接口：
  - GET /api/v1/deals
    - 参数：currency_code?, start?, end?, status?, customer_id?, sales_rep_id?, page?, page_size?, sort?
    - 返回：分页列表，记录包含 currency_code、amount_minor、deal_date 等
  - POST /api/v1/deals
    - 请求体：{ amount: number(主单位), currency_code: string, deal_date: ISO8601, ... }
    - 后端将主单位转换为 minor 存储；或前端直接传 minor（推荐统一传主单位，后端转换）
  - PUT /api/v1/deals/{id}、DELETE /api/v1/deals/{id}
- 校验：
  - currency_code 必须是 ISO 4217；通过 currency_meta 定位 exponent；amount 主单位转换为 minor：amount_minor = round(amount * 10^exponent)

### 3.2 统计接口（含分币与基准）
- 路由前缀示例：/api/v1/deals/summary 或 /api/v1/reports/deals
- GET /api/v1/deals/summary
  - 参数：
    - start=YYYY-MM-DD, end=YYYY-MM-DD（必填）
    - group_by=month|currency|month,currency（默认 month,currency）
    - base_currency?=USD|CNY|...
    - include_fx=true|false（默认 false）
    - strict_fx=true|false（默认 false，表示缺汇率可回退并返回 warnings）
  - 返回：
    ```
    {
      "range": {...},
      "group_by":"month,currency",
      "base_currency":"USD" | null,
      "include_fx":true | false,
      "results":[
        {
          "month":"2026-01",
          "currency":"USD",
          "revenue_gross_minor":123456,
          "deduction_rate":0.15,
          "deduction_minor":18518,
          "cost_minor":90000,
          "profit_minor":14938,
          "profit_in_base_minor": 14938 (若 include_fx=true 且 base_currency=USD)
        },
        ...
      ],
      "warnings":[{"type":"MISSING_FX","date":"2026-01-02","pair":"USD/CNY","message":"..."}]
    }
    ```
- 错误与边界：
  - start > end：400
  - 缺失汇率且 strict_fx=true：422
  - 不支持的 currency_code/base_currency：400
- 防混算保护：
  - 未传 base_currency 且 include_fx=true 时，返回 400（或自动置 include_fx=false，并在 warnings 中说明，建议 400 更清晰）
  - 服务层断言：若响应为分币结构，禁止在服务层对不同 currency 的 minor 直接求和。

---

## 4) 前端改造方案

### 4.1 Deals 列表/录入页面
- 新增“货币选择器”（默认 USD），采用 ISO 4217 列表；输入金额以主单位（可带两位小数）；
- 提交时由前端统一转换为 minor 传给后端，或传主单位由后端转换（两种可选，建议由后端统一转换避免前端/多端不一致）。
- 列表展示：
  - 金额显示使用 Intl.NumberFormat，按 currency_code 与 exponent 格式化（USD 显示两位，JPY 显示 0 位）。
  - 列表行展示 currency badge，避免误读。

### 4.2 统计展示
- 默认“分币 tabs”或分组卡片：
  - Tab: USD、CNY、JPY...；每个 Tab 内部的月度折线/柱状图仅展示该币数据。
- “转为基准币显示”开关（可选）：
  - 用户显式选择 base_currency（如 USD），并勾选“按基准币显示”，前端在调用 summary 接口时带 base_currency & include_fx=true。
  - 显示单位与 tooltip 明确标注“基准币=USD”。
- Finance/Dashboard 对接：
  - 保持默认分币种展示；仅在显式切换为基准币模式时才显示汇总数值；不会回退到隐式跨币合计。

### 4.3 格式化与工具
- 新增 currency utils：
  - toMinor(amountMajor, exponent) -> number
  - formatMinor(amountMinor, currency_code, exponent, locale) -> string
- 错误/警告展示：
  - 若接口 warnings 非空（缺汇率等），在 UI 显示可关闭的提示条。

---

## 5) 迁移与兼容

### 5.1 数据迁移（如现有 deals 使用浮点/主单位）
- Alembic 迁移步骤：
  1) 新增列 amount_minor BIGINT NOT NULL DEFAULT 0、currency_code CHAR(3) NOT NULL、currency_exponent SMALLINT NOT NULL DEFAULT 2（临时默认）
  2) 数据回填：对每行按照 currency_code 的 exponent 进行 round(amount_major * 10^exponent) -> amount_minor
  3) 移除默认值 & 加非空约束；保留旧列 amount_major（若存在）一段时间，标注弃用，后续版本删除
- 索引与性能：
  - 索引 (currency_code, deal_date DESC) 覆盖统计常用过滤
  - 索引 (sales_rep_id, deal_date DESC) 满足 RBAC 下销售页检索
  - 需要高性能汇总时，可评估按月物化视图（分币）+ 定时刷新

### 5.2 兼容接口
- 如已有 /api/v1/deals/summary 的响应结构与本设计存在命名差异，建议在返回体同时保留旧字段一段时间（标注 deprecated），并新增新字段；前端同步适配。
- 历史数据缺失 currency_code 的情况：统一视为系统默认货币（需配置），或拒绝并提示修复脚本。

---

## 6) 安全与权限

- 复用现有 RBAC：
  - admin：读写全部（CRUD、统计、汇率管理）
  - finance：可读统计、可读写 deals（根据业务），可读汇率
  - sales：仅访问自己范围内 deals 与统计
- 日志与审计：
  - 保持现有操作日志对 deals 的 create/update/delete 记录
  - 汇率导入/变更（若引入）建议记录审计日志（可后续扩展）

---

## 7) Mock 与测试

### 7.1 Mock 样例结构（JSON）
- /backend/mock_data/deals.json（示例）
  ```json
  [
    {"id":1,"amount_minor":123400,"currency_code":"USD","currency_exponent":2,"deal_date":"2026-01-15T10:00:00Z","counterparty":"Acme US","status":"won"},
    {"id":2,"amount_minor":567800,"currency_code":"CNY","currency_exponent":2,"deal_date":"2026-02-02T08:00:00Z","counterparty":"Acme CN","status":"won"},
    {"id":3,"amount_minor":8900,"currency_code":"JPY","currency_exponent":0,"deal_date":"2026-03-05T12:00:00Z","counterparty":"Nippon Co","status":"won"}
  ]
  ```
- /backend/mock_data/fx_rates.json（示例）
  ```json
  [
    {"base_currency":"USD","quote_currency":"CNY","as_of_date":"2026-01-15","rate":7.10},
    {"base_currency":"USD","quote_currency":"CNY","as_of_date":"2026-02-02","rate":7.05},
    {"base_currency":"USD","quote_currency":"JPY","as_of_date":"2026-03-05","rate":150.50}
  ]
  ```

### 7.2 最少覆盖场景
- 单币：仅 USD，单月与跨月扣点（默认与配置生效）
- 多币：USD + CNY（默认分币展示，不合计）
- 基准币：base_currency=USD 包含 CNY→USD 换算（含缺失汇率回退/报错）
- 跨月：1–3 月，扣点比例不同（例如 15%、12%、18%）
- 舍入：不同 exponent 的金额转换与扣点/换算后的四舍五入一致性
- RBAC：sales 用户仅返回自身 deals 的统计

### 7.3 单元/集成测试建议
- 单元测试（services 层）：
  - 金额主单位↔最小单位转换正确（含 JPY 等 exponent=0）
  - 扣点/利润计算（币种内）与跨月分桶逻辑正确
  - 汇率换算：按日换算，缺失回填与 strict_fx 分支
- 集成测试（路由）：
  - /api/v1/deals CRUD 与列表过滤
  - /api/v1/deals/summary：分币响应、基准币模式、缺汇率 warnings/422
- 回归测试：
  - Finance 与 Dashboard 仍默认分币种显示；仅在显式开关下使用基准币模式
- 工具：pytest + httpx.AsyncClient；CI 中执行

---

## 8) 第三方与开源库建议

- 后端（Python/FastAPI）：
  - SQLAlchemy + Alembic（现有）
  - python-dateutil/day数处理；pytz/zoneinfo（Python3.9+）
  - decimal（内置）用于计算与舍入；最终存 minor int
- 前端（React + TS）：
  - dayjs（日期）
  - Intl.NumberFormat（货币格式化）
  - zod（可选）做表单校验
- 不引入重型“货币库”，以 minor int + exponent 简化并避免浮点

---

## 9) 错误处理与边界条件

- 汇率缺失：
  - include_fx=true 且 strict_fx=true：422 + 错误详情
  - include_fx=true 且 strict_fx=false：200 + warnings（列出缺失日期与币对；采用向后填充或跳过该日）
- 金额溢出：amount_minor 使用 BIGINT，计算中使用 Python int/Decimal，结果截断/溢出需断言并返回 400
- 非法 currency_code/base_currency：返回 400
- 时区：deal_date 用 UTC 存储；统计按 UTC 拆日/拆月，前端展示可转换为本地（文档标注口径）

---

## 10) 实施与落地清单（工程指引）

- 数据层：
  - 新增/迁移 deals 表至 amount_minor & currency_code & currency_exponent
  - 新增 fx_rates 表与唯一索引
  - 补充 monthly_deduction_rates 已有逻辑的跨月分桶（如未完善）
- 服务层：
  - 统一金额转换与舍入函数（to_minor、from_minor）
  - 扣点计算（先扣点后换算）与跨日/跨月聚合
  - 防混算保护（不带 base_currency 时禁止跨币合计）
- 路由层：
  - /api/v1/deals CRUD + 列表过滤
  - /api/v1/deals/summary 分币/基准币统计参数与响应模型（含 warnings）
- 前端：
  - Deals 录入：货币选择器 + 金额输入（主单位）
  - 列表/统计：分币 tabs；“按基准币显示”开关（可选）
  - 单位与 tooltip 明确标注
- 测试：
  - 单元 + 集成测试覆盖关键路径
- 文档：
  - 更新 API 文档与前端使用说明
  - 记录基准币模式与汇率缺失策略

---

## 11) 统一口径与示例

### 11.1 统一口径摘要
- 默认：分币展示与求和，不跨币合计
- 基准币：显式 base_currency + include_fx=true
- 扣点：按月扣点（先扣点后换算）
- 换算：按日汇率；缺失回退/报错策略可选
- 存储：minor int + currency_code + exponent

### 11.2 请求/响应示例

- 请求（分币统计）：
  ```
  GET /api/v1/deals/summary?start=2026-01-01&end=2026-03-31&group_by=month,currency&include_fx=false
  ```

- 响应（分币）：
  ```json
  {
    "range":{"start":"2026-01-01","end":"2026-03-31"},
    "group_by":"month,currency",
    "base_currency":null,
    "include_fx":false,
    "results":[
      {"month":"2026-01","currency":"USD","revenue_gross_minor":123456,"deduction_rate":0.15,"deduction_minor":18518,"cost_minor":90000,"profit_minor":14938},
      {"month":"2026-01","currency":"CNY","revenue_gross_minor":345600,"deduction_rate":0.15,"deduction_minor":51840,"cost_minor":200000,"profit_minor":93760}
    ],
    "warnings":[]
  }
  ```

- 请求（基准币统计）：
  ```
  GET /api/v1/deals/summary?start=2026-01-01&end=2026-03-31&group_by=month&base_currency=USD&include_fx=true&strict_fx=false
  ```

- 响应（基准币，示例）：
  ```json
  {
    "range":{"start":"2026-01-01","end":"2026-03-31"},
    "group_by":"month",
    "base_currency":"USD",
    "include_fx":true,
    "results":[
      {"month":"2026-01","profit_in_base_minor": 120345, "deduction_rate":0.15, "notes":"converted by daily fx"},
      {"month":"2026-02","profit_in_base_minor": 98876, "deduction_rate":0.12, "notes":"converted by daily fx"}
    ],
    "warnings":[{"type":"MISSING_FX","date":"2026-02-10","pair":"USD/CNY","message":"backfilled with previous available rate"}]
  }
  ```

---

## 12) 风险与后续优化

- 风险：
  - 历史数据缺少 currency_code 或 exponent 信息，需要清洗/回补
  - 汇率缺失或不稳定数据源导致统计不一致；需明确数据来源与刷新频率
  - 跨日换算性能：长区间需要日级拆分，建议增加缓存或物化结果
- 优化：
  - 增量物化视图：按日/按月、分币与基准币两条线
  - 汇率管理后台（导入、查看、覆盖策略配置）
  - 指标预计算 + 事件驱动（新交易/变更触发对应桶增量更新）

---

本设计为 Deals 模块多币种支持的统一方案，后续工程实现应严格遵循本文“默认分币、不隐式合计、先扣点后换算”的口径，并在接口与前端明确标注单位与基准，保证统计与展示一致性。