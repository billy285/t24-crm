# Media operations UI refinement — deployed and accepted for this scope

Application `835be7a06d614e11080274426d8110797f53b5ef`, frontend `40f5a63a9156`,
was deployed by root with carrier `3c132016e231e89cd3e8ada4b0bca6b1d3ce0fa5`.
The exact source delta is 11 presentation/test paths, including six reviewed
new frontend/test files. Navigation overlays, the workspace toolbar, priority
presentation and automation-summary hierarchy were refined; API contracts and
business logic were outside scope.

This was static-only. Existing hashed assets were retained, one Nginx public
root switched atomically and Nginx reloaded. Backend source `54e027a`, all 432
backend files, schema `i54af678a914` / 169 tables, runtime container `6f826ade`
including image/config/start time/restart count, all ordered environment values
and worker flags, credentials, private boundary, permissions and CSP remain
unchanged. No DB write/migration/restore, backend/worker restart or provider/
publication action was requested. Business rows were not read or frozen.

## Evidence

- [Final release status](final-release-status.json) records deployment checks
  separately from scoped production UI acceptance. It makes no whole-system
  UI score or all-pages acceptance claim.
- [Baseline](baseline.json):
  `338bef1356329348180bcab4648921687047d4bf464ece3f38cdf46fec7d0c33`.
  Baseline application/frontend are `68fa858` / `6f71217e47f1`; backend source is
  separately pinned to `54e027a`.
- [Independent prepared review](prepared-review.json), canonical receipt:
  `e4998c3917f4e8ded7b3d03929565ef7ebff7eae5c6c49a671f83a1c9528486b`.
- [Deployed transport receipt](deployed.json), independently recomputed:
  `f8981993bc44c7286fcd84111d728a3a0fe381853e5495e584a108ac247475f4`.
- New static inventory:
  `30bf67da0e214b8f3e21a040f7b046eb46ae0665b2a1057c072f54468571dfe0`.
- Nginx config:
  `7465f221c0c3b0be761401035e12a123628771ddb9643bda68d31cfcbb34c67a`.

Canonical server hashes use sorted JSON, indent 2, trailing LF; exclude
`receipt_sha256` from the transport envelope. Prepared/deployed immutable
boundaries are identical and all frozen carrier bytes were rechecked locally.
Generation-time `executed:false` command manifests are retained unchanged.

## Validation boundaries

The reused release suite passed 97 tests plus six subtests. Independent review
checked the split frontend/backend baselines, exact additions allowlist and
single-load helper adaptation. Root reported 173 focused application checks,
3083 Vite modules, zero ESLint errors and two pre-existing Layout warnings.

The local synthetic fixture renders real Layout, DesktopBusinessNavigation,
BrowserRouter and the full MediaOperations page, including task-detail and
content-plan dialogs and single-store rules. Roles and API data remain mocked,
providers are disconnected and native unload prompts are absent. Actual DTO
verifiers checked owner/staff/empty/partial responses; its local write-free
bundle passed with 1773 modules. This is synthetic evidence, not production
account or provider acceptance. Root production acceptance passed for this release scope: 1280×800 loaded
43 merchants, with the normal automation summary collapsed. Opening business
navigation preserved the 964px stage width; dialog semantics, inert background
and Escape dismissal worked. Central review and one Instagram monthly detail
loaded 12 items through GET requests without a requested application mutation.
At 390×844, document scroll width stayed 390 and new buttons/inputs/selects were
at least 44px high. At 320×740, the 188px month input stayed within its card;
after main scroll 655, navigation top stayed 77 and toolbar top 137. Advanced
filters opened and closed, and the console showed zero errors. This acceptance
covers this release, not the whole site or every role/permission with real
accounts. Private screenshots and detailed UI records remain local outputs.

Recovery retains the previously reviewed protections: only known old/new config
bytes, known-prefix temporary cleanup, unconditional old-config reload even
after a previous reload failure, then live old-frontend/CSP verification. It
never restores the database or overwrites unknown configuration.

All cloud execution and production UI acceptance belong to root. This audit
contains no merchant names, captions or private screenshots. Real publication
still requires owner confirmation.
