import { expect, type Page } from '@playwright/test';

export const base = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
export const screenshots = process.env.T24_UI_SCREENSHOT_DIR;
export const day = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
type Employee = { id: number; name: string; role: string; status: string };
type Lead = { id: number; business_name: string; phone: string; country: string; industry?: string; industry_group?: string; enrichment_summary?: { interest_product_names: string[] }; status: string; do_not_contact: boolean; is_blacklisted: boolean; converted_customer_id?: number; next_follow_up_at?: string };
type Task = { contact_queue?: { timezone_group: string; in_contact_window: boolean }; task_id: number; task_status: string; priority: string; queue_category: string; lead: Lead };
export const employee: Employee = { id: 27, name: '模拟销售甲', role: 'sales', status: 'active' };
const records = (salesId = 27): Task[] => [0, 1].map(index => ({
  task_id: 901 + index, task_status: 'pending', priority: 'normal', queue_category: 'new',
  lead: { id: (salesId === 27 ? 501 : 601) + index, business_name: `${salesId === 27 ? '甲' : '乙'}商家${index + 1}`, phone: '+1 202 555 0123', country: 'US', status: 'new', do_not_contact: false, is_blacklisted: false },
}));

export async function fixture(page: Page, options: { user?: Employee; industryChoice?: boolean; multiClaim?: boolean; completedFirst?: boolean; manualLead?: boolean; empty?: boolean; failRead?: boolean; failFirstSave?: boolean; failReadAfterSave?: boolean; protected?: boolean } = {}) {
  let user = options.user || employee;
  const data = new Map([[27, options.empty ? [] : records()], [28, records(28)]]);
  if (options.industryChoice) {
    const tasks = data.get(27)!;
    tasks.push({ ...tasks[0], task_id: 903, lead: { ...tasks[0].lead, id: 503, business_name: '未拨美业' } });
    tasks.forEach(task => { task.lead.industry_group = 'beauty'; task.lead.industry = '美业'; });
    tasks[1].lead.next_follow_up_at = '2025-01-01T08:00:00Z';
    tasks[1].lead.status = 'follow_up';
  }
  if (options.completedFirst) data.get(27)![0].task_status = 'completed';
  if (options.protected) {
    data.get(27)![0].lead.do_not_contact = true;
    data.get(27)![1].lead.converted_customer_id = 800;
  }
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const reads: string[] = [];
  let failRead = options.failRead || false;
  let lastSalesId = 27;
  let attempts = 0;
  await page.addInitScript(value => {
    localStorage.setItem('emp_auth_token', 'sales-nine-local-token');
    localStorage.setItem('token', 'sales-nine-local-token');
    if (!localStorage.getItem('emp_auth_data')) localStorage.setItem('emp_auth_data', JSON.stringify(value));
  }, user);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!['GET', 'HEAD'].includes(request.method())) {
      writes.push({ path, body: request.postDataJSON() });
      if (path.endsWith('/emp-auth/login')) return route.fulfill({ json: { token: 'sales-nine-local-token', employee: user } });
      if (path.endsWith('/emp-auth/logout') || path.endsWith('/emp-auth/set_refresh')) return route.fulfill({ json: {} });
      if (options.industryChoice && path.endsWith('/workbench/prepare-industry')) {
        expect(url.searchParams.get('industry')).toBe('restaurant');
        expect(url.searchParams.get('target_date')).toBe(day());
        expect(url.searchParams.get('timezone_group')).toBe('mountain');
        expect(url.searchParams.get('window_only')).toBe('true');
        expect(url.searchParams.get('batch_size')).toBe(options.multiClaim ? '100' : '1');
        expect(url.searchParams.has('sales_employee_id')).toBe(false);
        const tasks = data.get(27)!;
        tasks[2] = { ...tasks[2], task_id: 904, contact_queue: { timezone_group: 'mountain', in_contact_window: true }, lead: { ...tasks[2].lead, id: 504, business_name: '新餐厅', industry: '中餐厅', industry_group: 'restaurant', enrichment_summary: { interest_product_names: ['新媒体代运营'] } } };
        if (options.multiClaim) tasks.push({ ...tasks[2], task_id: 905, lead: { ...tasks[2].lead, id:505, business_name:'第二家餐厅' } });
        const ids = options.multiClaim ? [504,505] : [504];
        return route.fulfill({ json: { industry: 'restaurant', created: ids.length, replaced: 1, total: tasks.length, pending_in_industry: ids.length, reason: 'queued', queued_lead_ids: ids, ready_lead_ids: [], message: `已补充 ${ids.length} 家餐厅` } });
      }
      if (options.manualLead && path.endsWith('/workbench/manual-task/503')) {
        const tasks = data.get(27)!;
        const task = { ...records()[0], task_id: 903, lead: { ...records()[0].lead, id: 503, business_name: '名下待联系商家' } };
        if (!tasks.some(item => item.task_id === task.task_id)) tasks.push(task);
        return route.fulfill({ json: { lead_id: 503, task_id: 903, sales_employee_id: 27, task_date: url.searchParams.get('target_date') } });
      }
      if (options.manualLead && path.endsWith('/workbench/tasks/903/dial-started')) {
        return route.fulfill({ json: { lead_id: 503, phone: '+12025550123', dial_attempt_id: 44 } });
      }
      const result = path.match(/\/workbench\/tasks\/(\d+)\/result$/);
      const task = result && data.get(lastSalesId)?.find(item => item.task_id === Number(result[1]));
      if (!task || task.task_status !== 'pending' || task.lead.do_not_contact || task.lead.converted_customer_id) return route.fulfill({ status: 409, json: { detail: '本地测试拒绝额外写入' } });
      attempts++;
      if (options.failFirstSave && attempts === 1) return route.fulfill({ status: 503, json: { detail: '模拟保存失败' } });
      const body = request.postDataJSON();
      task.task_status = 'completed';
      task.lead.status = ({ callback: 'follow_up', interested: 'interested', appointment: 'appointment', do_not_contact: 'blocked' } as Record<string, string>)[body.outcome] || 'contacted';
      task.lead.do_not_contact = body.outcome === 'do_not_contact';
      task.lead.next_follow_up_at = body.next_follow_up_at;
      if (options.failReadAfterSave) failRead = true;
      return route.fulfill({ json: { message: '通话结果已记录', task_id: task.task_id, lead_id: task.lead.id, lead: task.lead, status: task.lead.status, next_follow_up_at: task.lead.next_follow_up_at } });
    }
    reads.push(path + url.search);
    let response: unknown = { items: [], total: 0 };
    if (path.endsWith('/emp-auth/me')) response = user;
    else if (path.endsWith('/workbench/owned')) {
      const id = Number(url.searchParams.get('sales_employee_id'));
      const tasks = data.get(id) || [];
      const rows = tasks.map(task => ({ lead: task.lead, task_id: task.task_id, task_status: task.task_status, can_start: task.task_status === 'pending', unavailable_reason: null,
        contact_queue: { local_time: '2026-11-17T21:30:00-08:00', in_contact_window: false, next_window_at: '2026-11-18T10:00:00-08:00' } }));
      const assigned = options.manualLead && id === 27 && !tasks.some(t => t.lead.id === 503) ? [...rows, { ...rows[0], lead: { ...records()[0].lead, id: 503, business_name: '名下待联系商家' }, task_id: null, task_status: null }] : rows;
      const target = Number(url.searchParams.get('lead_id'));
      const view = url.searchParams.get('view');
      const items = view === 'assigned' ? assigned.filter(r => !target || r.lead.id === target) : [];
      response = { sales_employee_id: id, target_date: url.searchParams.get('target_date'), counts: { assigned: assigned.length, pending: tasks.filter(t => t.task_status === 'pending').length, callable: 0 }, items, total: items.length, has_more: false };
    }
    else if (options.industryChoice && path.endsWith('/workbench/industry-stock')) response = {
      industry: 'restaurant', contact_start: 10, contact_end: 18, total: 40, in_window: 20,
      zones: ['eastern', 'central', 'mountain', 'pacific'].map(group => ({
        group, total: 10, in_window: 5, local_times: group === 'mountain' ? ['09:30', '10:30'] : ['12:30'] })) };
    else if (options.manualLead && path.endsWith('/sales-leads/503')) response = { ...records()[0].lead, id: 503, business_name: '名下待联系商家', assigned_sales_id: 27 };
    else if (path.endsWith('/sales-leads/assignees')) response = [{ id: 27, name: '模拟销售甲' }, { id: 28, name: '模拟销售乙' }];
    else if (path.endsWith('/sales-leads/workbench/today')) {
      if (failRead) return route.fulfill({ status: 503, json: { detail: '模拟任务读取失败' } });
      const salesId = user.role === 'sales' ? user.id : Number(url.searchParams.get('sales_employee_id') || 27);
      lastSalesId = salesId;
      const tasks = data.get(salesId) || [];
      const completed = tasks.filter(task => task.task_status === 'completed').length;
      response = { salesperson: { id: salesId, name: '模拟销售' }, target_date: url.searchParams.get('target_date'), quota: options.industryChoice ? 3 : 20, assigned_count: tasks.length, completed_count: completed, remaining_count: tasks.length - completed, is_target_complete: false,
        categories: { unfinished: tasks.length - completed, callback: 0, interested: 0, appointment: 0, new: tasks.length }, performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items: tasks };
    } else if (path.endsWith('/dashboard/management')) response = { target_date: url.searchParams.get('target_date'), owner_attention: { overdue_followups: 0, high_intent_stale: 0 } };
    else if (path.endsWith('/merchant-pool/stats')) response = { pending: 0 };
    else if (path.endsWith('/dashboard/call-report')) response = { period: { start_date: day(), end_date: day() }, source: { status: 'verified' }, summary: { connected: 0 } };
    else if (path.endsWith('/ringcentral/status')) response = { configured: false, connected: false };
    else if (path.endsWith('/ringcentral/calls/recent')) response = { available: false, sync_status: 'waiting' };
    else if (path.endsWith('/call-history')) response = [];
    else if (path.endsWith('/app-config/sales/quick-note-templates')) response = {
      revision: 'a'.repeat(64),
      templates: [
        ['gatekeeper', '前台／老板不在', '前台接听，老板不在。'],
        ['english', '英文沟通', '对方讲英文，暂未能有效沟通。'],
        ['owner_interested', '老板有兴趣／忙', '老板有兴趣，目前比较忙。'],
        ['materials', '先看资料', '希望先看资料，关注：____。'],
        ['do_not_contact', '要求不再联系', '对方明确要求不再联系。'],
      ].map(([id, label, text]) => ({id, label, text, enabled: true, industry: 'all', remind_do_not_contact: id === 'do_not_contact'})),
    };
    else if (path.includes('/app-config')) response = { items: {} };
    else if (path.endsWith('/sales-knowledge/articles')) response = { items: [], categories: [] };
    await route.fulfill({ json: response });
  });
  return {
    writes, reads, recover: () => { failRead = false; },
    setUser: async (value: Employee) => { user = value; await page.evaluate(value => localStorage.setItem('emp_auth_data', JSON.stringify(value)), value); },
    changeLead: (id: number) => { data.get(27)![0].lead = { ...data.get(27)![0].lead, id, business_name: '重新分配后的商家' }; },
  };
}

export async function open(page: Page, width = 1440, query = '?sales_employee_id=27') {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 1000 });
  await page.goto(`${base}/sales-workbench${query}`);
  await expect(page.getByLabel('沟通记录', { exact: true })).toBeVisible();
}
export const notes = (page: Page) => page.getByLabel('沟通记录', { exact: true });
export const save = (page: Page) => page.getByRole('button', { name: '保存并下一位', exact: true });
export const key = (leadId = 501, userId = 27, salesId = 27) => `t24:sales-call-draft:v2:${userId}:${salesId}:${leadId}:${day()}:task:901`;
