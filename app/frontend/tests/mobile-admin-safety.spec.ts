import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const admin = { id: 1, name: '手机安全管理员', role: 'admin', status: 'active' };

async function fulfillJson(route: Route, data: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedAdmin(page: Page, role: 'admin' | 'super_admin' = 'admin') {
  const employee = { ...admin, role };
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'mobile-admin-token');
    window.localStorage.setItem('token', 'mobile-admin-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, employee);
    if (path === '/api/v1/payroll') return fulfillJson(route, {
      sheet: { id: 1, month: '2026-08', status: 'draft', currency: 'CNY' },
      items: [],
      totals: { gross: 0, deductions: 0, net: 0 },
    });
    if (path.endsWith('/payroll/employees')) return fulfillJson(route, []);
    if (path.includes('/reports/profit-monthly.json')) return fulfillJson(route, []);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, { items: [] });
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
}

function managementProfitRow(yearMonth: string, closeStatus: 'open' | 'locked') {
  return {
    year_month: yearMonth,
    project_contribution_usd: 100,
    project_contribution_cny: 700,
    company_expense_usd: 0,
    company_expense_cny: 50,
    exchange_rate: 7,
    payroll_cost_cny: 100,
    payroll_source: 'locked',
    recognized_service_revenue_usd: 200,
    recognized_service_revenue_cny: 1400,
    cash_service_revenue_usd: 200,
    cash_service_revenue_cny: 1400,
    ad_spread_usd: 0,
    ad_spread_cny: 0,
    refunds_usd: 0,
    refunds_cny: 0,
    stripe_fee_usd: 0,
    stripe_fee_cny: 0,
    customer_cost_usd: 0,
    customer_cost_cny: 0,
    channel_commission_usd: 0,
    channel_commission_cny: 0,
    recognized_revenue_cny_equivalent: 1400,
    cash_revenue_cny_equivalent: 1400,
    total_cost_cny_equivalent: 150,
    cash_profit_cny: 1250,
    exchange_rate_source: '测试锁定汇率',
    exchange_rate_status: 'locked',
    formal_profit_cny: 1250,
    status: 'ready',
    close_status: closeStatus,
  };
}

function managementDecisionPayloads() {
  return {
    classification: {
      start_date: '2026-01-01', write_enabled: true,
      summary: {
        customers: 0, payments: 0, subscriptions: 0, warning_counts: {}, review_counts: {},
        project_count: 0, active_project_count: 0, at_risk_project_count: 0, multi_project_customers: 0,
        project_line_counts: {}, project_status_counts: {}, anomaly_count: 0, high_anomaly_count: 0,
        risk_reminder_count: 0, line_metrics: {}, multi_project_combinations: {},
      },
      items: [], projects: [], anomalies: [], recommendations: [],
    },
    automation: {
      summary: { total: 0, open: 0, in_progress: 0, resolved: 0, open_task_count: 0, category_counts: {}, severity_counts: {} },
      items: [], schedule: { enabled: true, timezone: 'Asia/Shanghai', hour: 8, next_run_at: '2026-08-17T00:00:00Z', auto_stop_enabled: false },
      write_enabled: true,
    },
    growth: {
      period: { start_date: '2026-01-01', end_date: '2026-08-16' },
      formal_monthly_profit: {
        definition: '测试经营利润口径', cash_definition: '测试现金口径', accounting_note: '仅用于手机安全回归', missing_rate_months: [],
        summary: { label: '2026', start_month: '2026-01', end_month: '2026-08', month_count: 8, ready_month_count: 8, locked_month_count: 1, recognized_revenue_cny: 1400, cash_revenue_cny: 1400, total_cost_cny: 150, operating_profit_cny: 1250, cash_profit_cny: 1250, operating_margin: 0.89, status: 'ready' },
        quarterly: [], yearly: [],
        data_quality: { payments_with_service_period: 1, payments_using_receipt_month: 0, unlinked_payment_count: 0, locked_month_count: 1 },
        rows: [managementProfitRow('2026-06', 'locked'), managementProfitRow('2026-07', 'open')],
      },
      unit_economics: { definition: '测试', guardrails: [], totals: {}, unallocated: {}, coverage: { direct_projects: 0, inferred_projects: 0, projects_without_finance_data: 0 }, business_lines: [], projects: [] },
      customer_health: { summary: {}, auto_stop_enabled: false, updated_through: '2026-08-16', items: [] },
      team_capacity: { settings: { project_capacity_target: 12, capacity_warning_ratio: 0.8 }, summary: { active_projects: 0, unassigned_projects: 0, overdue_rate: 0, near_or_over_capacity: 0 }, employees: [], sales_lead_capacity: {}, recommendations: [] },
    },
  };
}

test('手机直接访问设置、权限和工资时只显示安全说明', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  const sensitiveRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/\/api\/v1\/(?:payroll(?:\/|$)|admin\/(?:settings|ai-settings)$|app-config\/(?:customer_code_settings|company_info|dict_config|dashboard_config|reminder_config|security_config|notification_config|export_config|role_permissions)$)/.test(path)) {
      sensitiveRequests.push(path);
    }
  });
  for (const [path, title] of [
    ['/settings', '全局设置请在电脑端处理'],
    ['/permissions', '权限管理请在电脑端处理'],
    ['/payroll', '工资处理请在电脑端完成'],
  ] as const) {
    await page.goto(`${baseUrl}${path}`);
    await expect(page.getByRole('heading', { name: title })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /保存权限配置|确认工资表|确认发放并锁定/ })).toHaveCount(0);
    await expect(page.getByRole('switch')).toHaveCount(0);
    await expect(page.getByText('工资表与人力成本')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  }
  await page.waitForTimeout(100);
  expect(sensitiveRequests).toEqual([]);
});

test('员工手机版只展示目录与概览，不暴露账号高风险操作', async ({ page }) => {
  await seedAdmin(page);
  await page.route(/\/api\/v1\/entities\/employees/, route => fulfillJson(route, {
    items: [{ id: 2, employee_code: 'EMP002', name: '手机员工卡片', role: 'sales', department: 'sales', position: 'specialist', status: 'active', phone: '555-0100', supervisor: '销售主管' }],
  }));
  await page.goto(`${baseUrl}/employees`);

  await expect(page.getByText('手机版提供员工目录与工作概览')).toBeVisible();
  await expect(page.getByTestId('employee-mobile-cards')).toContainText('手机员工卡片');
  await expect(page.getByRole('button', { name: '更多员工操作：手机员工卡片' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '添加员工' })).toHaveCount(0);
  await page.getByRole('button', { name: /查看概览/ }).click();
  await expect(page.getByText('手机员工卡片')).toBeVisible();
  await expect(page.getByRole('button', { name: /编辑|客户交接|重置密码|办理离职|停用|启用|转正/ })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /编辑|客户交接|重置密码|办理离职|停用|启用|转正/ })).toHaveCount(0);
  await expect(page.getByText('登录用户名:')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('分润中心手机版只加载结算摘要且不挂载任何变更控件', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  let optionsRequests = 0;
  await page.route(/\/api\/v1\/commissions\/options/, async route => {
    optionsRequests += 1;
    await fulfillJson(route, { employees: [], customers: [], business_lines: [], products: [], engagements: [] });
  });
  await page.route(/\/api\/v1\/commissions\/dashboard/, route => fulfillJson(route, {
    summary: {
      partner_count: 1,
      active_partner_count: 1,
      pending_count: 1,
      currencies: { USD: { confirmed_expense: 10, payable: 0, paid: 0 } },
      accounting_rule: '佣金独立计提',
      quality: { issue_count: 1, high_count: 1, covered_count: 1, examined_count: 2, coverage_rate: 50 },
    },
    quality_issues: [{ key: 'q1', type: 'missing', severity: 'high', title: '待补归属', description: '需要处理' }],
    partners: [{ id: 7, partner_code: 'P007', name: '手机渠道', partner_type: 'partner', status: 'active', joined_at: '2026-01-01' }],
    agreements: [],
    attributions: [],
    entries: [{ id: 1, partner_name: '手机渠道', customer_id: 1, customer_name: '手机客户', payment_id: 1, entry_type: 'first_order', status: 'pending_confirmation', service_month: '2026-08', occurred_at: '2026-08-01', currency: 'USD', gross_receipt_amount: 100, eligible_service_amount: 100, contract_rate: 0.1, inactivity_months: 0, activity_multiplier: 1, commission_amount: 10 }],
  }));

  await page.goto(`${baseUrl}/commissions`);
  await expect(page.getByRole('heading', { name: '渠道与分润中心' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '手机版为只读结算摘要' })).toBeVisible();
  await expect(page.getByRole('tab')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /新增渠道|新增协议版本|客户归属|扫描实收与退款|一键补齐归属|确认|转应付|已发放|作废|暂停结算|停止合作|恢复合作/ })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /新增渠道|新增协议版本|客户归属|扫描实收与退款|一键补齐归属|确认|转应付|已发放|作废|暂停结算|停止合作|恢复合作/ })).toHaveCount(0);
  expect(optionsRequests).toBe(0);
  await expectNoHorizontalOverflow(page);
});

test('客户生命周期手机版只读查看轨迹且不挂载状态变更操作', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  await page.route(/\/api\/v1\/customer-lifecycle\/overview/, route => fulfillJson(route, {
    summary: { new_customers: 1, existing_customers: 0, current_active: 1, current_paused: 0, pending_stop: 0, stopped: 0, retention_3m: null, retention_6m: null, retention_12m: null, median_tenure_months: null, average_stopped_months: null, review_count: 0 },
    cohorts: [],
    monthly: [],
    stop_reasons: [],
    customers: [{ id: 1, customer_id: 1, business_name: '生命周期手机客户', customer_code: 'C001', cycle_number: 1, first_payment_id: 1, started_at: '2026-01-01', status: 'active', start_source: 'payment', start_locked: true, cooperation_months: 7, sales_person: '销售A', needs_review: false, closure_needed: false }],
  }));
  await page.route(/\/api\/v1\/customer-lifecycle\/customers\/1/, route => fulfillJson(route, {
    customer: { id: 1, business_name: '生命周期手机客户', customer_code: 'C001' },
    cycles: [],
    events: [],
  }));

  await page.goto(`${baseUrl}/customer-lifecycle`);
  await expect(page.getByText('生命周期手机客户')).toBeVisible();
  await expect(page.getByRole('button', { name: /回溯历史|暂停|待停止|恢复|停止|同步闭环|重新合作|修正日期/ })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /回溯历史|暂停|待停止|恢复|停止|同步闭环|重新合作|修正日期/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /经营分类与项目/ })).toHaveCount(0);
  await page.getByRole('button', { name: '查看生命周期轨迹' }).click();
  await expect(page.getByRole('dialog')).toContainText('生命周期手机客户');
  await expect(page.getByRole('dialog').getByRole('button', { name: '确认' })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('财务手机深链接进入记账工作台且只开放三类新增操作', async ({ page }) => {
  await seedAdmin(page);
  const nonGetRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/') && request.method() !== 'GET') nonGetRequests.push(`${request.method()} ${path}`);
  });
  await page.route(/\/api\/v1\/entities\/payments(?:\/all)?/, route => fulfillJson(route, {
    items: [{ id: 1, customer_id: 1, customer_name: '手机财务客户', amount_due: 198, amount_paid: 198, management_amount: 198, ads_recharge_amount: 0, currency: 'USD', payment_date: '2026-08-01', created_at: '2026-08-01' }],
    total: 1,
  }));
  await page.route(/\/api\/v1\/deductions-monthly(?:\?|$)/, route => fulfillJson(route, [{ year_month: '2026-08', rate: 0.15 }]));
  await page.goto(`${baseUrl}/finance?tab=income`);

  await expect(page.getByRole('heading', { name: '财务工作台' })).toBeVisible();
  await expect(page.getByText('快速记一笔')).toBeVisible();
  await expect(page.getByRole('button', { name: '录入收款' })).toBeVisible();
  await expect(page.getByRole('button', { name: '客户支出' })).toBeVisible();
  await expect(page.getByRole('button', { name: '运营支出' })).toBeVisible();
  await expect(page.getByRole('button', { name: '导出 Excel' })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /导出 CSV|导出 Excel|记录退款|确认退款入账|新增月结|保存月结|确认关账|重新打开|删除收款|删除支出|编辑收款|编辑支出/ })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: /收入管理/ })).toHaveCount(0);
  await page.getByRole('button', { name: '录入收款' }).click();
  let mobileDialog = page.getByRole('dialog');
  await expect(mobileDialog.getByRole('heading', { name: '录入收款' })).toBeVisible();
  await expect(mobileDialog.getByRole('button', { name: '确认录入收款' })).toBeVisible();
  await expect(mobileDialog).toHaveCSS('border-radius', '0px');
  const paymentDialogBounds = await mobileDialog.boundingBox();
  expect(paymentDialogBounds?.width).toBeGreaterThanOrEqual(389);
  expect(paymentDialogBounds?.height).toBeGreaterThanOrEqual(843);
  await mobileDialog.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '客户支出' }).click();
  mobileDialog = page.getByRole('dialog');
  await expect(mobileDialog.getByRole('heading', { name: '录入客户支出' })).toBeVisible();
  await expect(mobileDialog.getByRole('button', { name: '确认录入客户支出' })).toBeVisible();
  await mobileDialog.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '运营支出' }).click();
  mobileDialog = page.getByRole('dialog');
  await expect(mobileDialog.getByRole('heading', { name: '录入运营支出' })).toBeVisible();
  await expect(mobileDialog.getByRole('button', { name: '确认录入运营支出' })).toBeVisible();
  await mobileDialog.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.waitForTimeout(100);
  expect(nonGetRequests).toEqual([]);
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/finance?tab=company_expense`);
  await page.getByRole('button', { name: '录入运营支出' }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: '录入运营支出' })).toBeVisible();
  nonGetRequests.length = 0;

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('dialog').getByRole('heading', { name: '录入运营支出' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '录入收款' })).toBeVisible();
  await expect(page.getByRole('button', { name: '客户支出' })).toBeVisible();
  await expect(page.getByRole('button', { name: '运营支出' })).toBeVisible();
  await expect(page.locator('button').filter({ hasText: /导出 CSV|导出 Excel|记录退款|确认退款入账|新增月结|保存月结|确认关账|重新打开/ })).toHaveCount(0);
  await page.waitForTimeout(100);
  expect(nonGetRequests).toEqual([]);
});

test('财务手机工作台可以提交收款、客户支出和运营支出', async ({ page }) => {
  await seedAdmin(page);
  const writes: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && [
      '/api/v1/entities/payments',
      '/api/v1/entities/expenses',
      '/api/v1/entities/company_expenses',
    ].includes(path)) writes.push(path);
  });
  await page.route(/\/api\/v1\/entities\/customers(?:\/all)?/, route => fulfillJson(route, {
    items: [{ id: 1, business_name: '手机记账客户', contact_name: '测试联系人', interested_packages: 'Google Ads' }],
    total: 1,
  }));
  await page.route(/\/api\/v1\/entities\/payments(?:\/all)?/, route => fulfillJson(route, { items: [], total: 0 }));

  await page.goto(`${baseUrl}/finance`);

  await page.getByRole('button', { name: '录入收款' }).click();
  let dialog = page.getByRole('dialog');
  await dialog.locator('select').nth(0).selectOption('1');
  await dialog.locator('input[type="number"]').fill('120');
  await dialog.getByPlaceholder('例如：Google Ads 管理').fill('Google Ads');
  await dialog.getByRole('button', { name: '确认录入收款' }).click();
  await expect(dialog).toHaveCount(0);

  await page.getByRole('button', { name: '客户支出' }).click();
  dialog = page.getByRole('dialog');
  await dialog.locator('select').nth(0).selectOption('1');
  await dialog.locator('input[type="number"]').fill('35');
  await dialog.getByRole('button', { name: '确认录入客户支出' }).click();
  await expect(dialog).toHaveCount(0);

  await page.getByRole('button', { name: '运营支出' }).click();
  dialog = page.getByRole('dialog');
  await dialog.locator('input[type="number"]').fill('88');
  await dialog.getByRole('button', { name: '确认录入运营支出' }).click();
  await expect(dialog).toHaveCount(0);

  expect(writes).toEqual([
    '/api/v1/entities/payments',
    '/api/v1/entities/expenses',
    '/api/v1/entities/company_expenses',
  ]);
  await expectNoHorizontalOverflow(page);
});

test('合伙人门户在手机使用客户和分润卡片而不是宽表', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  await page.route(/\/api\/v1\/commissions\/my-dashboard/, route => fulfillJson(route, {
    portal_mode: 'owner_readonly',
    available_partners: [{ id: 7, name: '渠道七', partner_code: 'P007', status: 'active' }],
    partner: { id: 7, name: '渠道七', partner_code: 'P007', status: 'active', joined_at: '2026-01-01' },
    summary: { active_customer_count: 1, cooperation_customer_count: 1, renewal_attention_count: 1, stopped_customer_count: 0, ledger_count: 1, currencies: { USD: { pending: 50, confirmed: 100, payable: 30, paid: 70 } }, status_updated_at: '2026-08-16T00:00:00Z' },
    customers: [{ row_key: 'c1', attribution_id: 1, customer_code: 'C001', customer_name: '手机渠道客户', engagement_name: '专业套餐', cooperation_status: 'active_paid', renewal_status: 'expiring_soon', next_due_at: '2026-08-20', last_receipt_at: '2026-07-20', commission_impact: '续费成功后按协议计提', effective_from: '2026-01-01', is_active: true }],
    entries: [{ id: 1, customer_name: '手机渠道客户', entry_type: 'renewal', status: 'payable', service_month: '2026-08', currency: 'USD', eligible_service_amount: 249, contract_rate: 0.2, inactivity_months: 0, activity_multiplier: 1, commission_amount: 49.8 }],
    agreements: [{ id: 1, version: 1, business_line_name: '代运营', product_name: '专业套餐', first_order_rate: 0.5, renewal_rate: 0.2, activity_decay: { 6: 0 }, refund_guard_days: 30, effective_from: '2026-01-01', status: 'active' }],
  }));
  await page.goto(`${baseUrl}/partner-portal`);

  await expect(page.getByRole('region', { name: '手机端客户与分润明细' })).toContainText('手机渠道客户');
  await expect(page.getByRole('region', { name: '手机端客户与分润明细' })).toContainText('USD 49.80');
  await expect(page.locator('table')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('经营总览按老板待办、经营规模和生命周期建立清晰层级', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  await page.setViewportSize({ width: 1440, height: 900 });
  const payloads = managementDecisionPayloads();
  (payloads.classification.summary as any) = {
    ...payloads.classification.summary,
    warning_counts: { needs_classification: 26 },
    review_counts: { pending: 0 },
    project_count: 39,
    active_project_count: 29,
    multi_project_customers: 1,
    high_anomaly_count: 0,
    risk_reminder_count: 3,
  };
  (payloads.classification as any).recommendations = [{
    level: 'info', title: '继续积累真实项目数据', message: '先补齐首次收款日期、负责人和停止原因。',
  }];
  await page.route(/\/api\/v1\/management-decisions\/classification-review/, route => fulfillJson(route, payloads.classification));
  await page.route(/\/api\/v1\/management-decisions\/automation\/overview/, route => fulfillJson(route, payloads.automation));
  await page.route(/\/api\/v1\/management-decisions\/growth-dashboard/, route => fulfillJson(route, payloads.growth));

  await page.goto(`${baseUrl}/management-decisions`);

  const decisionHeading = page.getByRole('heading', { name: '老板待办与决策建议' });
  const scaleHeading = page.getByRole('heading', { name: '经营规模' });
  const lifecycleHeading = page.getByRole('heading', { name: '各业务生命周期信号' });
  await expect(decisionHeading).toBeVisible();
  await expect(scaleHeading).toBeVisible();
  await expect(lifecycleHeading).toBeVisible();
  await expect(page.getByText('继续积累真实项目数据')).toBeVisible();
  await expect(page.getByText('当前无需处理')).toHaveCount(2);
  await expect(page.locator('details').filter({ hasText: '安全审核模式' })).not.toHaveAttribute('open', '');
  await expect(page.getByLabel('辅助管理入口')).toBeVisible();

  const [decisionBox, scaleBox, lifecycleBox] = await Promise.all([
    decisionHeading.boundingBox(), scaleHeading.boundingBox(), lifecycleHeading.boundingBox(),
  ]);
  expect(decisionBox?.y).toBeLessThan(scaleBox?.y || 0);
  expect(scaleBox?.y).toBeLessThan(lifecycleBox?.y || 0);
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel('辅助管理入口')).toBeHidden();
  await expectNoHorizontalOverflow(page);
});

test('经营决策手机版不挂载高级月结控件且不会触发写请求', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  const payloads = managementDecisionPayloads();
  const project = {
    id: 41, customer_id: 9, customer_name: '视口切换客户', customer_code: 'C009',
    business_line: { code: 'managed_service', name: '代运营' },
    product: { code: 'managed_service_legacy', name: '专业套餐' },
    package_name: '专业套餐', status: 'active_paid', billing_cycle: 'monthly',
    collection_method: 'other', currency: 'USD', paid_started_at: '2026-08-01',
    industry: '餐饮', sales_person: '销售甲',
  };
  (payloads.classification as any).projects = [project];
  (payloads.classification as any).items = [{
    customer_id: 9, customer_code: 'C009', customer_name: '视口切换客户', industry: '餐饮',
    review_status: 'pending', review_note: '', customer_lifecycle: { status: 'active', started_at: '2026-08-01' },
    warnings: [], suggestions: [{
      business_line: 'managed_service', product_code: 'managed_service_legacy', product_name: '专业套餐',
      paid_started_at: '2026-08-01', billing_cycle: 'monthly', currency: 'USD',
      source_payment_ids: [], source_subscription_ids: [], basis: [],
    }], projects: [project],
  }];
  await page.route(/\/api\/v1\/management-decisions\/classification-review/, route => fulfillJson(route, payloads.classification));
  await page.route(/\/api\/v1\/management-decisions\/automation\/overview/, route => fulfillJson(route, payloads.automation));
  await page.route(/\/api\/v1\/management-decisions\/growth-dashboard/, route => fulfillJson(route, payloads.growth));
  const writeRequests: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/v1/management-decisions/') && request.method() !== 'GET') {
      writeRequests.push(`${request.method()} ${path}`);
    }
  });

  await page.goto(`${baseUrl}/management-decisions?section=insights`);
  await expect(page.getByRole('heading', { name: '经营健康与决策' })).toBeVisible();
  await expect(page.getByText('公司人民币利润已使用独立报表')).toBeVisible();
  await expect(page.locator('details').filter({ hasText: '高级财务月结与历史口径' })).toHaveCount(0);
  await expect(page.locator('button').filter({ hasText: /锁定|确认月结|重新打开/ })).toHaveCount(0);
  expect(writeRequests).toEqual([]);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  const advancedClose = page.locator('details').filter({ hasText: '高级财务月结与历史口径' });
  await expect(advancedClose).toBeVisible();
  await advancedClose.locator('summary').click();
  await expect(advancedClose.getByRole('button', { name: '重新打开' })).toBeVisible();
  await expect(advancedClose.getByRole('button', { name: '确认月结' })).toBeVisible();

  await page.goto(`${baseUrl}/management-decisions?section=history`);
  await page.getByRole('button', { name: '开始审核' }).click();
  await expect(page.getByRole('dialog').getByText('分类与项目确认')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText('分类与项目确认')).toHaveCount(0);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${baseUrl}/management-decisions?section=projects`);
  await page.getByRole('button', { name: '更改状态' }).click();
  await expect(page.getByRole('dialog').getByText('更改项目状态')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText('更改项目状态')).toHaveCount(0);
  expect(writeRequests).toEqual([]);
});

test('430px 安全页面保持只读提示且无横向溢出', async ({ page }) => {
  await seedAdmin(page, 'super_admin');
  await page.setViewportSize({ width: 430, height: 932 });

  for (const [path, title] of [
    ['/settings', '全局设置请在电脑端处理'],
    ['/permissions', '权限管理请在电脑端处理'],
    ['/payroll', '工资处理请在电脑端完成'],
  ] as const) {
    await page.goto(`${baseUrl}${path}`);
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});
