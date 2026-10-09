import { expect, test, type Page, type Route } from '@playwright/test';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '../src/lib/business-date';

const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5199';
const admin = { id: 1, name: '体验验证管理员', role: 'super_admin', status: 'active' };
const source = { id: 2, name: '交接员工 A', role: 'sales', status: 'active' };
const target = { id: 3, name: '交接员工 B', role: 'sales', status: 'active' };
const customer = { id: 11, customer_code: 'C11', business_name: '体验验证商家', status: 'closed', contact_name: '张先生', phone: '7737437663', country: 'US', sales_person: source.name, sales_employee_id: 2 };
const json = (route: Route, data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
const sleep = (time: number) => new Promise(resolve => setTimeout(resolve, time));
async function auth(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'customer-workflow-test'); localStorage.setItem('token', 'customer-workflow-test'); localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, admin);
}
async function defaults(route: Route) {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith('/emp-auth/me')) return json(route, admin);
  if (path.includes('/app-config')) return json(route, { items: {} });
  if (path.includes('/entities/employees')) return json(route, { items: [admin, source, target], total: 3 });
  if (path.includes('/entities/customers')) return json(route, { items: [customer], total: 1 });
  if (path.includes('/admin/settings')) return json(route, { backend_vars: {}, frontend_vars: {} });
  if (path.includes('/admin/ai-settings')) return json(route, { enabled: false, provider: 'openai', api_key_set: false });
  if (path.includes('/product-plans')) return json(route, { business_lines: [], products: [], plans: [] });
  return json(route, { items: [], total: 0 });
}

test('商机时间按北京时间序列化，UTC 无偏移时间也按数据库 UTC 显示', () => {
  expect(parseBusinessDateTimeInput('2026-10-10T09:30')).toBe('2026-10-10T01:30:00.000Z');
  expect(formatBusinessDateTimeInput('2026-10-10T01:30:00')).toBe('2026-10-10T09:30');
  expect(formatBusinessDateTimeInput('2026-10-10T01:30:00Z')).toBe('2026-10-10T09:30');
  expect(() => parseBusinessDateTimeInput('2026-02-30T09:30')).toThrow();
});

test('回访保存成功、后续任务失败时只重试安排，不重复保存原回访', async ({ page }) => {
  await auth(page);
  let originalUpdates = 0; let taskCreates = 0; let nextCreates = 0;
  const row: any = { id: 21, customer_id: 11, employee_id: 2, employee_name: source.name, callback_date: '2026-10-10', callback_type: 'satisfaction', status: 'completed', result: 'need_followup', content: '确认客户需求', next_callback_date: '2026-10-11' };
  const callbackRows = [row]; const tasks: any[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname; const method = route.request().method();
    if (path.endsWith('/customer_callbacks/21') && method === 'PUT') { originalUpdates++; Object.assign(row, route.request().postDataJSON()); return json(route, row); }
    if (path.endsWith('/customer_callbacks') && method === 'POST') { nextCreates++; const next = { ...route.request().postDataJSON(), id: 22 }; callbackRows.push(next); return json(route, next); }
    if (path.includes('/customer_callbacks')) return json(route, { items: callbackRows, total: callbackRows.length });
    if (path.endsWith('/tasks') && method === 'POST') { taskCreates++; if (taskCreates === 1) return json(route, { detail: '模拟后续任务暂不可用' }, 500); const task = { ...route.request().postDataJSON(), id: 31 }; tasks.push(task); return json(route, task); }
    if (path.includes('/entities/tasks')) return json(route, { items: tasks, total: tasks.length });
    return defaults(route);
  });
  await page.goto(`${base}/callbacks?callback_id=21`);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '编辑回访记录' })).toBeVisible();
  await dialog.locator('textarea').fill('确认客户需求，需要跟进运营资料');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('已保存');
  expect(originalUpdates).toBe(1);
  await dialog.getByRole('button', { name: '重试后续安排' }).click();
  await expect(dialog).toHaveCount(0);
  expect(originalUpdates).toBe(1); expect(taskCreates).toBe(2); expect(nextCreates).toBe(1);
  expect(tasks[0].assignee_id).toBe(2);
});

test('编辑任务取消时保留草稿，明确放弃后才关闭，不写数据', async ({ page }) => {
  await auth(page); const writes: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => { if (route.request().method() !== 'GET') writes.push(route.request().url()); return defaults(route); });
  await page.goto(`${base}/tasks`);
  await page.getByRole('button', { name: '新建任务', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('input').first().fill('尚未保存的交付任务');
  page.once('dialog', prompt => prompt.dismiss());
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog.locator('input').first()).toHaveValue('尚未保存的交付任务');
  page.once('dialog', prompt => prompt.accept());
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0); expect(writes).toEqual([]);
});

test('员工交接读取超过一页的五类归属，部分失败后只转交剩余事项', async ({ page }) => {
  await auth(page);
  const rows: Record<string, any[]> = {
    customers: Array.from({ length: 205 }, (_, i) => ({ ...customer, id: i + 100 })),
    tasks: [{ id: 500, assignee_id: 2, assignee_name: source.name, status: 'pending', title: '交接待办' }],
    service_tasks: [{ id: 600, assignee_name: source.name, status: 'pending', task_name: '交接交付' }],
    service_progresses: [{ id: 700, ops_person: source.name, service_stage: 'account_setup', customer_name: '交接服务' }],
  };
  const project: any = { id: 800, owner_employee_id: 2, sales_employee_id: 2, status: 'active_paid', customer_name: '交接项目' };
  const customerWrites: number[] = []; let taskAttempts = 0; let projectCalls = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url()); const method = route.request().method(); const path = url.pathname;
    if (path.endsWith('/handoff-projects')) { projectCalls++; project.owner_employee_id = 3; project.sales_employee_id = 3; return json(route, { transferred_count: 1, remaining_count: 0 }); }
    if (path.endsWith('/management-decisions/engagements')) return json(route, { items: [project], total: 1 });
    const match = /\/entities\/(customers|tasks|service_tasks|service_progresses)(?:\/(all|\d+))?$/.exec(path);
    if (match) {
      const entity = match[1]; const id = match[2]; const collection = rows[entity];
      if (method === 'PUT') {
        if (entity === 'tasks' && ++taskAttempts === 1) return json(route, { detail: '模拟任务交接暂不可用' }, 500);
        const row = collection.find(item => String(item.id) === id); Object.assign(row, route.request().postDataJSON());
        if (entity === 'customers') customerWrites.push(Number(id));
        return json(route, row);
      }
      const skip = Number(url.searchParams.get('skip') || 0); const limit = Number(url.searchParams.get('limit') || 1000);
      return json(route, { items: collection.slice(skip, skip + limit), total: collection.length });
    }
    return defaults(route);
  });
  await page.goto(`${base}/employees`);
  await page.getByRole('button', { name: `更多员工操作：${source.name}` }).click();
  await page.getByRole('menuitem', { name: '客户交接' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: '确认交接 209 项' })).toBeVisible();
  await dialog.locator('select').selectOption('3');
  await dialog.getByRole('button', { name: '确认交接 209 项' }).click();
  await expect(dialog.getByRole('alert')).toContainText('模拟任务交接暂不可用');
  await expect(dialog.getByRole('status')).toContainText('本次已完成 205 项');
  expect(customerWrites).toHaveLength(205); expect(new Set(customerWrites).size).toBe(205);
  await dialog.getByRole('button', { name: '重新核对清单' }).click();
  await dialog.getByRole('button', { name: '确认交接 4 项' }).click();
  await expect(dialog.getByRole('button', { name: '已全部交接' })).toBeVisible();
  expect(customerWrites).toHaveLength(205); expect(taskAttempts).toBe(2); expect(projectCalls).toBe(1);
  expect(project.owner_employee_id).toBe(3); expect(project.sales_employee_id).toBe(3);
});

test('员工切换时迟到的旧响应不能覆盖新员工资料', async ({ page }) => {
  await auth(page); let customerReads = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/entities/customers/all')) {
      if (++customerReads === 1) { await sleep(400); return json(route, { items: [{ ...customer, business_name: '旧员工慢资料' }], total: 1 }); }
      return json(route, { items: [{ ...customer, id: 12, business_name: '新员工快资料', sales_person: '历史员工名称', sales_employee_id: 3 }], total: 1 });
    }
    return defaults(route);
  });
  await page.goto(`${base}/employees`);
  await page.getByRole('cell', { name: source.name, exact: true }).click();
  await page.getByRole('button', { name: '返回列表' }).click();
  await page.getByRole('cell', { name: target.name, exact: true }).click();
  await page.getByRole('tab', { name: /负责客户/ }).click();
  await expect(page.getByRole('cell', { name: '新员工快资料' })).toBeVisible();
  await sleep(500);
  await expect(page.getByRole('cell', { name: '旧员工慢资料' })).toHaveCount(0);
});

test('跨角色权限草稿显示完整变更摘要，保存期间不能再次提交', async ({ page }) => {
  await auth(page); let saves = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/app-config/role_permissions') && route.request().method() === 'PUT') { saves++; await sleep(400); return json(route, route.request().postDataJSON()); }
    return defaults(route);
  });
  await page.goto(`${base}/permissions`);
  const role = page.getByLabel('当前配置角色');
  const toggle = page.getByRole('switch', { name: '客户管理页面访问', exact: true });
  await toggle.click(); await role.selectOption('ops'); await toggle.click();
  await expect(page.locator('details').filter({ hasText: '保存前核对' })).toContainText('2 个角色');
  const save = page.getByRole('button', { name: '保存权限配置', exact: true });
  await save.click(); await expect(page.getByRole('button', { name: '保存中…' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '保存权限配置' })).toBeDisabled(); expect(saves).toBe(1);
});

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


async function managementFixture(page: Page, width = 390) {
  await auth(page, width); const payloads: any = managementDecisionPayloads(); const writes: string[] = [];
  payloads.classification.projects = Array.from({ length: 35 }, (_, i) => ({ id: i + 101, customer_id: i + 11, customer_name: `完整项目商家 ${i + 1}`, customer_code: `C${i + 11}`, business_line: { code: 'beauty_os', name: '美业 OS' }, product: { code: 'beauty_os', name: '预约系统' }, package_name: '完整服务套餐', status: 'active_paid', billing_cycle: 'monthly', currency: 'USD', paid_started_at: '2026-10-01', industry: '美业', sales_person: source.name }));
  payloads.growth.os_paid_customer_evidence = { verified_customer_ids_by_business_line: { beauty_os: [11], restaurant_os: [] } };
  payloads.growth.unit_economics.projects = payloads.classification.projects.map((row: any) => ({ project_id: row.id, customer_id: row.customer_id, customer_name: row.customer_name, business_line: '美业 OS', business_line_code: 'beauty_os', product_name: '预约系统', status: 'active_paid', confidence: 'direct', metrics: [{ currency: 'USD', service_revenue: 128, ad_spread: 12, service_refunds: 9, stripe_fee_burden: 3, customer_cost: 28, channel_commission: 8, contribution_profit: 92, contribution_margin: .66 }] }));
  payloads.growth.customer_health.items = payloads.classification.projects.slice(0, 25).map((row: any) => ({ project_id: row.id, customer_id: row.customer_id, customer_name: row.customer_name, business_line: '美业 OS', product_name: '预约系统', project_status: 'active_paid', owner_name: source.name, score: 40, level: 'risk', reasons: [{ code: 'overdue', points: 10, message: '客户回访待完成' }], recommended_action: '联系客户并安排回访' }));
  payloads.growth.team_capacity.employees = [{ employee_id: 2, employee_name: source.name, role: '运营', active_projects: 9, capacity_target: 12, utilization: .75, open_tasks: 16, overdue_tasks: 2, open_delivery_tasks: 8, overdue_delivery_tasks: 1, capacity_level: 'normal' }];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    if (route.request().method() !== 'GET') writes.push(route.request().url());
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/classification-review')) return json(route, payloads.classification);
    if (path.endsWith('/automation/overview')) return json(route, payloads.automation);
    if (path.endsWith('/growth-dashboard')) return json(route, payloads.growth);
    return defaults(route);
  });
  return writes;
}

test('320px 项目明细能翻完所有记录，OS 实收下钻只展示核验客户', async ({ page }) => {
  const writes = await managementFixture(page, 320);
  await page.goto(`${base}/management-decisions?section=projects&businessLine=os&returnTo=%2Fcompany-roadmap`);
  const cards = page.getByTestId('mobile-management-projects');
  await expect(cards.locator('article')).toHaveCount(20);
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(cards.locator('article')).toHaveCount(15);
  await expect(cards.getByRole('link', { name: '完整项目商家 35', exact: true })).toBeVisible();
  const link = await cards.getByRole('link', { name: '完整项目商家 35', exact: true }).getAttribute('href');
  expect(new URL(link!, 'https://t24-crm.local').searchParams.get('returnTo')).toContain('projectPage=2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '返回公司经营路线', exact: true })).toBeVisible();
  await page.goto(`${base}/management-decisions?section=projects&businessLine=os&paidOnly=1`);
  await expect(cards.locator('article')).toHaveCount(1);
  await expect(cards).toContainText('完整项目商家 1');
  await expect(cards).not.toContainText('完整项目商家 2');
  expect(writes).toEqual([]);
});

test('手机经营分析展开完整收支、风险和产能，展示原始金额且全程只读', async ({ page }) => {
  const writes = await managementFixture(page);
  await page.goto(`${base}/management-decisions?section=insights`);
  await page.getByText('项目收支明细', { exact: true }).click();
  const cards = page.getByTestId('mobile-project-economics');
  await expect(cards.locator('article')).toHaveCount(30);
  const first = cards.locator('article').first();
  for (const text of ['服务收入', '投流差价', '服务退款', '手续费', '客户成本', '渠道分润', '贡献利润', '利润率', '$128.00', '$92.00']) await expect(first).toContainText(text);
  await page.getByRole('button', { name: '继续显示项目（剩余 5）' }).click();
  await expect(cards.locator('article')).toHaveCount(35);
  await page.getByRole('button', { name: '继续显示风险项目（剩余 5）' }).click();
  await expect(page.locator('#decision-health').getByRole('link', { name: '完整项目商家 25' })).toBeVisible();
  await page.getByText('员工产能明细', { exact: true }).click();
  await expect(page.getByTestId('mobile-employee-capacity')).toContainText('16 / 2');
  await expect(page.getByTestId('mobile-employee-capacity')).toContainText('8 / 1');
  await expect(page.getByRole('button', { name: /更改状态|确认月结|锁定/ })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
});

test('服务看板准确打开既有服务，推进前展示未完成任务，取消不写入', async ({ page }) => {
  await auth(page); const updates: any[] = [];
  const progress: any = { id: 701, customer_id: 11, customer_name: customer.business_name, service_type: 'social_media', service_stage: 'account_setup', progress_percent: 40, ops_person: admin.name, sales_person: source.name, package_name: '基础服务', issue_status: 'none' };
  const tasks = [{ id: 901, service_progress_id: 701, customer_id: 11, task_name: '核对首批上线内容', task_type: 'other', assignee_name: admin.name, status: 'pending', priority: 'medium' }];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/service_progresses/701')) { if (route.request().method() === 'PUT') { updates.push(route.request().postDataJSON()); Object.assign(progress, updates.at(-1)); } return json(route, progress); }
    if (path.includes('/service_progresses')) return json(route, { items: [progress], total: 1 });
    if (path.includes('/service_tasks')) return json(route, { items: tasks, total: 1 });
    return defaults(route);
  });
  await page.goto(`${base}/service-board?progress_id=701&returnTo=%2Fsales%3Fstatus%3Dclosed`);
  await expect(page.getByRole('heading', { name: customer.business_name, exact: true })).toBeVisible();
  await expect(page.getByText('核对首批上线内容', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: /^推进到:/ }).click();
  let dialog = page.getByRole('dialog'); await expect(dialog).toContainText('当前仍有 1 项未完成任务');
  await dialog.getByRole('button', { name: '取消', exact: true }).click(); expect(updates).toEqual([]);
  await page.getByRole('button', { name: /^推进到:/ }).click();
  dialog = page.getByRole('dialog'); await dialog.getByRole('button', { name: '确认推进', exact: true }).click();
  await expect(dialog).toHaveCount(0); expect(updates).toHaveLength(1); expect(updates[0].service_stage).toBe('content_prep');
  await page.getByRole('button', { name: '返回成交客户', exact: true }).click();
  await expect(page).toHaveURL(/\/sales\?status=closed/);
});

test('运营结果先保存、下一步失败后关闭仍可补齐，不重复完成原任务', async ({ page }) => {
  await auth(page); let completedWrites = 0; let nextCreates = 0;
  const task: any = { id: 801, customer_id: 11, customer_name: customer.business_name, title: '核对本周服务结果', assignee_name: admin.name, assignee_id: 1, status: 'in_progress', priority: 'medium', task_type: 'follow_up', notes: '' };
  const tasks: any[] = [task];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/tasks/801') && route.request().method() === 'PUT') { completedWrites++; Object.assign(task, route.request().postDataJSON()); return json(route, task); }
    if (path.endsWith('/tasks') && route.request().method() === 'POST') { if (++nextCreates === 1) return json(route, { detail: '暂无法创建任务' }, 500); const created = { id: 802, ...route.request().postDataJSON() }; tasks.push(created); return json(route, created); }
    if (path.includes('/entities/tasks')) return json(route, { items: tasks, total: tasks.length });
    return defaults(route);
  });
  await page.goto(`${base}/operations-workbench`);
  await page.getByRole('button', { name: '填写处理结果', exact: true }).click();
  let dialog = page.getByRole('dialog'); await dialog.locator('textarea').fill('服务结果已核对，等待客户下周反馈');
  await dialog.getByRole('checkbox', { name: '安排下一步任务' }).check();
  await dialog.getByLabel('下一步事项').fill('下周客户反馈回访'); await dialog.getByLabel('截止日期 · 北京时间').fill('2026-10-12');
  await dialog.getByRole('button', { name: '完成并记录', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('处理结果已保存');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '补齐下一步安排', exact: true }).click();
  dialog = page.getByRole('dialog'); await dialog.getByRole('button', { name: '重试下一步安排', exact: true }).click();
  await expect(dialog).toHaveCount(0); expect(completedWrites).toBe(1); expect(nextCreates).toBe(2); expect(tasks[1].assignee_id).toBe(1);
});

test('新员工已创建但密码失败时保留事实，重试只设置密码', async ({ page }) => {
  await auth(page); let creates = 0; let passwordAttempts = 0;
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/entities/employees') && route.request().method() === 'POST') { creates++; return json(route, { id: 501, ...route.request().postDataJSON() }); }
    if (path.endsWith('/emp-auth/set-password')) { if (++passwordAttempts === 1) return json(route, { detail: '密码服务暂不可用' }, 500); return json(route, { success: true }); }
    return defaults(route);
  });
  await page.goto(`${base}/employees`); await page.getByRole('button', { name: '添加员工', exact: true }).click();
  const dialog = page.getByRole('dialog'); await dialog.locator('input').nth(1).fill('密码恢复测试员工'); await dialog.locator('input[type=password]').fill('test-password-123');
  await dialog.getByRole('button', { name: '保存', exact: true }).click(); await expect(dialog.getByRole('alert')).toContainText('员工已经创建');
  await dialog.getByRole('button', { name: '重试设置密码' }).click(); await expect(dialog).toHaveCount(0);
  expect(creates).toBe(1); expect(passwordAttempts).toBe(2);
});

test('手机空或部分系统配置可读未设置，不请求密钥、不产生写入', async ({ page }) => {
  await auth(page, 390); const errors: string[] = []; const forbidden: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => { const path = new URL(route.request().url()).pathname; if (route.request().method() !== 'GET' || /\/admin\/(settings|ai-settings)/.test(path)) forbidden.push(path); if (path.includes('/app-config/')) return json(route, { value: {} }); return defaults(route); });
  await page.goto(`${base}/settings`);
  await expect(page.getByTestId('mobile-settings-summary')).toBeVisible(); await expect(page.getByText('未设置', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveCount(0); expect(errors).toEqual([]); expect(forbidden).toEqual([]);
});

test('跨手机断点保留公司、环境与AI草稿，既有运行配置不会因resize重新读取', async ({ page }) => {
  await auth(page); let envReads = 0; let aiReads = 0; let companyReads = 0; const writes: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') writes.push(path);
    if (path.endsWith('/app-config/company_info')) { companyReads++; return json(route, { value: { name: '已保存公司', address: '', phone: '', email: '', website: '', description: '' } }); }
    if (path.endsWith('/admin/settings')) { envReads++; return json(route, { backend_vars: { SAFE_TEST_SETTING: { key: 'SAFE_TEST_SETTING', value: 'saved-value', description: '仅测试参数' } }, frontend_vars: {} }); }
    if (path.endsWith('/admin/ai-settings')) { aiReads++; return json(route, { enabled: false, provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'test-saved-model', api_key_set: false, api_key_preview: '' }); }
    return defaults(route);
  });
  await page.goto(`${base}/settings`);
  await page.getByRole('tab', { name: '公司信息', exact: true }).click();
  await page.getByPlaceholder('公司名称', { exact: true }).fill('未保存公司草稿');
  await page.getByRole('tab', { name: '环境配置', exact: true }).click();
  await page.getByPlaceholder('请输入 SAFE_TEST_SETTING').fill('unsaved-runtime-draft');
  await page.getByRole('tab', { name: 'AI配置', exact: true }).click();
  const model = page.getByPlaceholder('gpt-5.4-mini');
  await model.fill('test-unsaved-model');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('mobile-settings-summary')).toContainText('未保存公司草稿');
  await expect(page.getByText('有未保存的修改，草稿已保留。请回到电脑布局继续保存。')).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('tab', { name: '公司信息', exact: true }).click();
  await expect(page.getByPlaceholder('公司名称', { exact: true })).toHaveValue('未保存公司草稿');
  await page.getByRole('tab', { name: '环境配置', exact: true }).click();
  await expect(page.getByPlaceholder('请输入 SAFE_TEST_SETTING')).toHaveValue('unsaved-runtime-draft');
  await page.getByRole('tab', { name: 'AI配置', exact: true }).click();
  await expect(model).toHaveValue('test-unsaved-model');
  expect(envReads).toBe(1); expect(aiReads).toBe(1); expect(companyReads).toBe(1); expect(writes).toEqual([]);
});
