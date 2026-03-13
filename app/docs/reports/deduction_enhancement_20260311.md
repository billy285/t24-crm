# Monthly Deduction Enhancement (2026-03-11)

What’s new
- Global default deduction rate endpoints:
  - GET /api/v1/deductions-monthly/default -> { rate: 0.15 }
  - PUT /api/v1/deductions-monthly/default -> update global default (0~1)
- CSV Import:
  - POST /api/v1/deductions-monthly/import (multipart/form-data)
  - Columns: year_month (YYYY-MM), rate (decimal e.g., 0.15)
  - overwrite=true|false for conflict strategy
- Audit Trail:
  - Table monthly_deduction_audits
  - Log actions: create|update|delete|import|default_update with actor_id, before_json, after_json, at

Permissions
- Only admin can write (create/update/delete/import/default_update).
- Non-admin users can read.

Frontend (Settings -> 月度扣点比例)
- Manage per-month rates (list/add/edit/delete).
- Set global default rate (% input, stored as decimal).
- Import CSV with overwrite toggle and result summary.

Profit Calculation (Finance)
- Monthly bucket, apply monthly rate if exists, else default 0.15.
- USD/CNY metrics remain split; no cross-currency mixing.

Mock
- Sample CSV: backend/mock_data/monthly_deduction_rates_sample.csv (12 months).
- Initialize data enabled; missing user_id auto-filled from ADMIN_USER_ID when needed.

Notes
- Restart backend to load the newly added routes if the service was already running without reload.