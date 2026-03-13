# Tasks 1,2,4 - MVP Implementation Plan (Max 8 code files)

Design goals
- Keep "keep logged in (30d)" and "cross-currency separation" unchanged.
- Add monthly profit export (CSV/Excel) with monthly deduction rates applied.
- Strengthen currency-aggregation protection.
- Enhance monthly deduction with default rate + CSV import + audit + admin-only writes.

Code files to create/modify (7 files)
1) backend/routers/reports_export.py
   - Endpoints:
     - GET /api/v1/reports/profit-monthly.csv
     - GET /api/v1/reports/profit-monthly.xlsx
   - Logic: Aggregate monthly revenue (payments), costs (expenses/customer in USD, company_expenses in CNY), apply per-month deduction_rate (from monthly_deduction_rates or default 0.15).
   - CSV with StreamingResponse; Excel with openpyxl.

2) backend/routers/finance_deduction.py (extend existing)
   - Existing: monthly_deduction_rates CRUD.
   - New:
     - GET /api/v1/deductions-monthly/default
     - PUT /api/v1/deductions-monthly/default
     - POST /api/v1/deductions-monthly/import (multipart CSV, columns: year_month, rate)
     - Create audit table monthly_deduction_audits; log create/update/delete/import/default_update with actor_id.
     - Admin-only write (create/update/delete/import/default_update), read open.

3) backend/tests/test_reports_and_deductions.py
   - Basic tests: list deductions 200; get default 200; export CSV 200; export Excel 200.
   - Edge: missing dates uses data range fallback.

4) backend/requirements.txt
   - Append: openpyxl>=3.1.2

5) frontend/src/lib/api.ts
   - Add helpers:
     - exportProfitMonthlyCsv({ start, end, currency?, base_currency? })
     - exportProfitMonthlyXlsx({ start, end, currency?, base_currency? })
     - getDefaultDeduction(), updateDefaultDeduction(rate)
     - importMonthlyDeductions(file, overwrite)

6) frontend/src/pages/MonthlyDeduction.tsx
   - Enhance:
     - Show default rate section (read/update) for admin.
     - CSV import (overwrite toggle) for admin.
     - Keep existing CRUD table.

7) frontend/src/pages/Finance.tsx (minimal)
   - Add two small handlers (download CSV/Excel) invoking api.ts helpers; render a simple fixed-position export panel to avoid layout coupling.

Notes and compromises
- Currency aggregation: export defaults to separate currency outputs; base_currency param accepted but FX conversion deferred (no fx_rates yet). This keeps protection intact.
- Tests are smoke-level to validate routing and basic headers; business correctness will be expanded after Bob’s FX design (Task 3).