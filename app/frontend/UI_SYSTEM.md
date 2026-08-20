# T24 CRM UI Design System

## Product character

T24 CRM should feel like a calm business operating system: clear, trustworthy and fast under daily workload. The interface uses a light neutral canvas, white work surfaces, a navy global navigation and cobalt blue for the single primary action. Dark surfaces are reserved for owner-level decisions and risk summaries.

## Foundations

| Foundation | Rule |
| --- | --- |
| Canvas | `#F3F6FB` |
| Surface | `#FFFFFF` |
| Primary text | `#0F172A` |
| Secondary text | `#334155` |
| Muted text | `#64748B` |
| Border | `#DFE5EE` |
| Primary action | `#2563EB`; hover `#1D4ED8` |
| Navigation | `#0B1730` |
| Positive / warning / danger | `#059669` / `#D97706` / `#E11D48` |
| Spacing | 4, 8, 12, 16, 20, 24, 32 px |
| Radius | 10 px control, 14 px card, 18 px major workspace |
| Type | Inter, PingFang SC and system sans; tabular numerals enabled |

Use shadows only to show hierarchy. Borders define most surfaces. A page should normally have one strong accent and one primary action.

## Page patterns

### Command center

Used by owner dashboard, finance overview and management decisions. Structure: compact decision hero, four headline metrics, priority work queue, then supporting detail. The dark hero is allowed here because it signals an executive decision surface.

### Directory

Used by customers, employees, contracts and service records. Structure: title and primary action, compact metrics, lifecycle segments, search/filter toolbar and a full-width records table. A record opens into a dedicated detail page or dialog; permanent right-side 360 panels are avoided because they reduce table working space.

### Workbench

Used by sales, merchant cleaning and operational execution. Structure: daily result header, left queue, central task surface and optional collapsible assistant. At laptop widths the assistant starts collapsed; when opened it overlays the task edge instead of compressing the main work area.

## Component rules

- Page header: one title, one-line explanation, one primary action. Secondary actions are grouped.
- Metric card: label, result and one explanatory line. No more than five headline metrics.
- Toolbar: search first, common filters next, advanced filters last. Active filter count must remain visible.
- Table: sticky header, compact rows, row hover, explicit empty/loading/error states and horizontal overflow only when necessary.
- Forms: labels stay visible; placeholder text never replaces a label. Save is primary, cancel is neutral.
- Status: green means successful/healthy, amber means attention, red means blocked/risk. Blue means action or selection, not status.
- Touch targets: minimum 44 px on mobile; desktop dense controls may be 32–40 px.
- Motion: 160–200 ms for hover and focus. Avoid decorative motion in task-heavy screens.

## Responsive behavior

- Mobile: single column, key action remains visible, batch and export controls move to desktop-only guidance where appropriate.
- Tablet/laptop: two-column workbenches; assistants and secondary inspectors collapse by default.
- Wide desktop: optional third workspace column appears at 1536 px and above.

## Adoption map

1. Foundation and global shell — implemented.
2. Owner command center, customer directory and sales workbench reference implementations — implemented.
3. Employee directory, merchant pool and knowledge library pattern adoption — implemented.
4. Finance, task collaboration and service delivery pattern adoption — implemented.
5. Deals, lifecycle, reporting, callbacks, payroll, settings and access-control adoption — implemented.
6. Final release review and production deployment — requires explicit approval.
