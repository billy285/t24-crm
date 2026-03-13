# 导出功能使用指南（追加说明 2026-03-11）

## 前端导出按钮位置与交互说明
- 位置：Finance 页面页眉右上角，和既有 ExportButton 同一水平区域（同一行并排）。
- 新增按钮：
  - 「导出 CSV」：按钮尺寸 size="sm"，outline 风格，点击后按当前页面的日期筛选导出 CSV。
  - 「导出 Excel」：按钮尺寸 size="sm"，主按钮样式（蓝色），点击后按当前页面的日期筛选导出 Excel。
- 加载/禁用：导出执行中按钮置为 disabled，避免重复点击。

## 参数映射规则
- 日期范围复用页面筛选：
  - 自定义时间段：使用「开始日期」「结束日期」作为 start/end。
  - 今日：使用当天日期作为 start 与 end。
  - 全部：自动从当前页面已加载的数据（payments.payment_date 与 expenses.expense_month）推断最早与最晚日期；若无法推断，则回退至当月整月。
- 币种：
  - 默认按“分币种导出”，未显式传递 base_currency。
  - 若未来启用“基准币开关”，则在前端传入 base_currency 值以按基准币导出。

## 文件命名规范
- CSV：profit-monthly_YYYYMMDD-YYYYMMDD.csv
- Excel：profit-monthly_YYYYMMDD-YYYYMMDD.xlsx

## 后端接口
- GET /api/v1/reports/profit-monthly.csv（参数：start、end、currency?、base_currency?）
- GET /api/v1/reports/profit-monthly.xlsx（参数：start、end、currency?、base_currency?）

## “按月明细”Tab 与口径说明
- 位置：Finance 页的 Tabs 新增 “按月明细”。
- 列：month、revenue_gross、扣点率(%)、扣点金额、cost、profit。
- 口径：默认按 USD 展示（不跨币混算）。如启用基准币开关（后续版本），会按 base_currency 展示。
- 同步：与页面筛选保持一致（自定义/今日/全部），导出按钮与本 Tab 共享同一筛选参数。
- 格式：金额千分位保留两位小数；扣点率以百分比显示。

## 异常与提示
- 网络或鉴权失败：提示“导出失败”，并在控制台输出错误详情以便排查。
- 路由未生效：请重启后端服务，确认 /health=200 且 /docs 可见导出路由。