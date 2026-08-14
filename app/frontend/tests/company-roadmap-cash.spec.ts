import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '测试管理员', role: 'admin', status: 'active' };
const now = new Date();
const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

const overviewFor = (month: string) => ({
  settings: {
    configured: true,
    target_start_date: '2026-01-01',
    target_end_date: '2030-12-31',
    five_year_profit_target_cny: 20_000_000,
    monthly_fixed_expense_cny: 30_000,
    cash_reserve_months: 6,
    cash_safety_target_cny: 180_000,
    default_usd_cny_rate: 6.7,
    current_focus: '',
  },
  accounts: [{
    id: 1,
    name: 'Mercury 运营账户',
    account_type: 'bank',
    currency: 'USD',
    masked_identifier: '•••• 2850',
    is_active: true,
    sort_order: 0,
    notes: null,
  }],
  cash_period: null,
  cash_history: [],
  restriction_categories: [{ value: 'tax_reserve', label: '税务预留' }],
  restriction_suggestions: [],
  unrecorded_suggestion_cny: 0,
  cash_health: {
    has_baseline: false,
    as_of_month: null,
    snapshot_status: null,
    snapshot_age_days: null,
    is_stale: false,
    free_cash_cny: null,
    safety_target_cny: 180_000,
    gap_to_safety_cny: null,
    runway_months: null,
    level: 'unknown',
    projections: [],
    projection_reason: '尚未形成已确认快照',
  },
  goal: {
    target_cny: 20_000_000,
    recognized_profit_cny: 0,
    progress_ratio: 0,
    remaining_cny: 20_000_000,
    remaining_months: 60,
    required_average_monthly_profit_cny: 333_333.33,
    ready_months: 0,
    total_months: 8,
    has_profit_data: false,
    is_complete_data: false,
    expected_profit_to_date_cny: 0,
    pace_gap_cny: 0,
    pace_status: 'data_incomplete',
  },
  operating_signals: {
    three_month_average_profit_cny: null,
    profit_sample_months: 0,
    active_managed_service_projects: 0,
    active_os_projects: 0,
    paid_os_projects: 0,
    paid_restaurant_os_projects: 0,
    paid_beauty_os_projects: 0,
    paid_os_customers: 0,
    paid_restaurant_os_customers: 0,
    paid_beauty_os_customers: 0,
    leading_os_code: 'restaurant_os',
    leading_os_name: '餐饮 OS',
    high_risk_project_count: 0,
    health_project_count: 0,
    high_risk_ratio: 0,
    active_employee_count: 1,
    team_capacity: {
      active_projects: 0,
      unassigned_projects: 0,
      near_or_over_capacity: 0,
      overdue_rate: 0,
      hiring_level: 'stable',
      hiring_title: '暂不扩编',
      hiring_message: '继续积累产能数据。',
      history_persisted: false,
      history_weeks: 0,
      observation_required_weeks: 4,
      hiring_gate_ready: false,
    },
  },
  milestones: [{ key: 'cash', label: '现金安全', status: 'current', target: '先建立可信底账' }],
  recommendation: {
    key: 'cash_baseline',
    level: 'warning',
    title: '先完成现金底账',
    why: '当前没有已确认快照',
    action: `核对 ${month} 账户余额`,
    decision: null,
  },
  definitions: {
    free_cash: '账户余额减去受限资金。',
    profit_vs_cash: '利润和现金分别核算。',
    data_boundary: '锁定后才进入经营决策。',
  },
});

async function mockRoadmapApi(page: Page, overviewHandler?: (route: Route, month: string) => Promise<void>) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'roadmap-test-token');
    window.localStorage.setItem('token', 'roadmap-test-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith('/emp-auth/me')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(employee) });
      return;
    }
    if (url.pathname.endsWith('/company-roadmap/overview')) {
      const month = url.searchParams.get('month') || currentMonth;
      if (overviewHandler) {
        await overviewHandler(route, month);
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overviewFor(month)) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}

test('空余额不会当作 0，确认 0 后按新契约保存', async ({ page }) => {
  let savedPayload: any = null;
  await mockRoadmapApi(page);
  await page.route(/\/api\/v1\/company-roadmap\/cash-periods\/\d{4}-\d{2}$/, async route => {
    savedPayload = route.request().postDataJSON();
    const month = route.request().url().match(/(\d{4}-\d{2})$/)?.[1] || currentMonth;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 9,
        version: 1,
        year_month: month,
        snapshot_date: `${month}-01`,
        status: 'draft',
        usd_cny_rate: 6.7,
        notes: null,
        balances: [{ account_id: 1, balance: 0, confirmed_zero: true }],
        restrictions: [],
        totals: { account_balance_cny: 0, restricted_cny: 0, free_cash_cny: 0 },
      }),
    });
  });

  await page.goto(`${baseUrl}/company-roadmap`);
  await expect(page.getByRole('heading', { name: '公司战略与里程碑' })).toBeVisible();
  for (const label of ['账户总余额', '受限资金', '真正可用现金', '安全线差额']) {
    await expect(page.getByText(label, { exact: true }).locator('..').getByText('待确认', { exact: true })).toBeVisible();
  }

  const balance = page.getByLabel('Mercury 运营账户 本期余额');
  await balance.fill('0');
  await expect(page.getByText('0 元必须勾选确认，不能把空白当作 0')).toBeVisible();
  await page.getByRole('button', { name: '保存草稿' }).click();
  await expect.poll(() => savedPayload).toBeNull();

  await page.getByText('本期已核对，余额确实为 0').click();
  await page.getByRole('button', { name: '保存草稿' }).click();
  await expect.poll(() => savedPayload).not.toBeNull();
  expect(savedPayload.version).toBe(0);
  expect(savedPayload.balances).toEqual([{ account_id: 1, balance: 0, confirmed_zero: true }]);
});

test('新增现金账户停留在当前页面并立即显示', async ({ page }) => {
  let created = false;
  const newAccount = {
    id: 2,
    name: '人民币运营账户',
    account_type: 'bank',
    currency: 'CNY' as const,
    masked_identifier: '•••• 8899',
    is_active: true,
    sort_order: 1,
    notes: null,
  };
  await mockRoadmapApi(page, async (route, month) => {
    const overview = overviewFor(month);
    if (created) overview.accounts.push(newAccount);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) });
  });
  await page.route(/\/api\/v1\/company-roadmap\/cash-accounts$/, async route => {
    created = true;
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ id: newAccount.id, account: newAccount, message: '现金账户已新增' }),
    });
  });

  await page.goto(`${baseUrl}/company-roadmap`);
  await page.getByRole('button', { name: '新增账户', exact: true }).click();
  await page.getByLabel('账户名称 *').fill(newAccount.name);
  await page.getByLabel('脱敏末位/简称').fill(newAccount.masked_identifier);
  await page.getByRole('button', { name: '保存账户' }).click();

  await expect(page).toHaveURL(/\/company-roadmap$/);
  await expect(page.getByRole('heading', { name: '公司战略与里程碑' })).toBeVisible();
  await expect(page.getByText(newAccount.name, { exact: true })).toBeVisible();
  await expect(page.getByLabel(`${newAccount.name} 本期余额`)).toBeVisible();
});

test('切换月份读取失败时不展示旧月份编辑数据', async ({ page }) => {
  await mockRoadmapApi(page, async (route, month) => {
    if (month === currentMonth) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overviewFor(month)) });
      return;
    }
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '测试读取失败' }) });
  });

  await page.goto(`${baseUrl}/company-roadmap`);
  await expect(page.getByLabel('Mercury 运营账户 本期余额')).toBeVisible();
  const targetMonth = currentMonth.endsWith('-01')
    ? `${Number(currentMonth.slice(0, 4)) - 1}-12`
    : `${currentMonth.slice(0, 5)}${String(Number(currentMonth.slice(5)) - 1).padStart(2, '0')}`;
  await page.getByLabel('现金快照月份').fill(targetMonth);
  await expect(page.getByText(`${targetMonth} 现金数据读取失败`)).toBeVisible();
  await expect(page.getByLabel('Mercury 运营账户 本期余额')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0);
});

test('保存成功但刷新失败时保留已保存状态并阻止重复提交', async ({ page }) => {
  let overviewReads = 0;
  let saveCount = 0;
  await mockRoadmapApi(page, async (route, month) => {
    overviewReads += 1;
    if (overviewReads === 1) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overviewFor(month)) });
      return;
    }
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '测试同步失败' }) });
  });
  await page.route(/\/api\/v1\/company-roadmap\/cash-periods\/\d{4}-\d{2}$/, async route => {
    saveCount += 1;
    const payload = route.request().postDataJSON();
    const month = route.request().url().match(/(\d{4}-\d{2})$/)?.[1] || currentMonth;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 10,
        version: 1,
        year_month: month,
        snapshot_date: payload.snapshot_date,
        status: 'draft',
        usd_cny_rate: payload.usd_cny_rate,
        notes: null,
        balances: payload.balances,
        restrictions: [],
        totals: { account_balance_cny: 670, restricted_cny: 0, free_cash_cny: 670 },
      }),
    });
  });

  await page.goto(`${baseUrl}/company-roadmap`);
  await page.getByLabel('Mercury 运营账户 本期余额').fill('100');
  const saveButton = page.getByRole('button', { name: '保存草稿' });
  await saveButton.click();
  await expect(page.getByText('数据已保存，但页面同步尚未完成')).toBeVisible();
  await expect(saveButton).toBeDisabled();
  expect(saveCount).toBe(1);
});
