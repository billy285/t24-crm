# Currency Aggregation Audit (Incremental) - 2026-03-11

Goals
- Maintain strict split of USD/CNY metrics; prevent implicit cross-currency sums.
- Require explicit base_currency parameter for any cross-currency aggregation (future FX design).

Backend Protections (current)
- Reports export returns per-currency rows by default.
- Profit calculation applies per-month deduction to USD revenue; company expenses (CNY) remain separate and labeled.
- Endpoints surface currency or currency_or_base field to prevent ambiguous rendering.

Frontend Changes (Finance/Dashboard)
- Clearly labeled USD vs CNY metrics and chart legends.
- Profit (USD) computed and displayed separately; CNY costs shown independently.
- Added export buttons (CSV/Excel) to obtain split reports.

Test Coverage (added/updated)
- /backend/tests/test_reports_and_deductions.py
  - Deductions list and default endpoints: 200
  - Profit exports CSV/XLSX: 200, correct content-types

Known Gaps
- base_currency accepted but FX conversion deferred until Deals multi-currency design (Task 3).
- Backend service restart required to load new routers in persistent environments.

Conclusion
- Cross-currency separation is enforced across backend responses and frontend presentation for current scope.
- Further FX conversion rules will be integrated after system design is finalized.