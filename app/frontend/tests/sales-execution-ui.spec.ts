import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5175';
const screenshotDir = process.env.T24_UI_SCREENSHOT_DIR;

const employee = { id: 27, name: '销售体验测试账号', role: 'sales', status: 'active' };
const articles = [
  {
    id: 1,
    category: '销售准备与开场',
    title: '免费分析型开场白',
    customer_question: '第一次联系商家怎么开场？',
    standard_answer: '您好，请问是老板吗？我今天看了一下您店里的线上情况，整理了几个免费的建议，想花一分钟跟您分享，看看对您有没有帮助。',
    action_steps: [],
    related_links: [],
    tags: ['开场白', '首次联系'],
    status: 'published',
    is_sensitive: false,
    sort_order: 10,
  },
  {
    id: 2,
    category: '套餐与报价',
    title: '客户说太贵如何回复？',
    customer_question: '客户觉得报价太贵，销售怎么推进？',
    standard_answer: '我理解您希望控制成本。我们先不只比较月费，想确认您更在意平台费用、人工时间、获客效果还是持续运营。我们会按您真正需要的平台和目标推荐合适方案。',
    action_steps: ['确认客户最在意的成本项', '按真实需求推荐方案'],
    escalation_rule: '涉及特殊折扣或价格承诺时，必须先由销售主管确认。',
    related_links: [],
    tags: ['价格', '异议处理'],
    status: 'published',
    is_sensitive: false,
    sort_order: 20,
  },
  {
    id: 3,
    category: '收款与付款',
    title: '客户怎么付款？',
    customer_question: '客户问可以用什么方式付款？',
    standard_answer: '系统服务可通过官网订阅页面付款，其他服务由财务发送对应付款说明。销售负责发送说明和记录反馈，是否到账只能由财务确认。',
    action_steps: ['确认客户购买的服务', '发送对应付款说明', '交由财务确认到账'],
    escalation_rule: '销售不能自行确认到账或复用其他客户的付款链接。',
    related_links: [],
    tags: ['付款', '财务确认'],
    status: 'published',
    is_sensitive: true,
    sort_order: 30,
  },
];

async function mockSalesApi(page: Page) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'sales-execution-ui-token');
    window.localStorage.setItem('token', 'sales-execution-ui-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data: unknown = {};

    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/sales-knowledge/articles')) {
      const query = (url.searchParams.get('query') || '').toLowerCase();
      const category = url.searchParams.get('category');
      const items = articles.filter(article => {
        const matchesQuery = !query || `${article.title} ${article.customer_question} ${article.standard_answer} ${article.tags.join(' ')}`.toLowerCase().includes(query);
        const matchesCategory = !category || article.category === category;
        return matchesQuery && matchesCategory;
      });
      data = { items, categories: Array.from(new Set(articles.map(article => article.category))) };
    } else if (path.endsWith('/sales-knowledge/questions')) data = { items: [] };
    else if (path.endsWith('/sales-leads/workbench/today')) data = {
      salesperson: { id: employee.id, name: employee.name },
      quota: 20,
      assigned_count: 1,
      completed_count: 0,
      remaining_count: 1,
      is_target_complete: false,
      categories: { unfinished: 1, callback: 0, interested: 0, appointment: 0, new: 1, retry: 0, recycled: 0, follow_up: 0 },
      performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 },
      items: [{
        task_id: 901,
        task_status: 'pending',
        priority: 'high',
        next_action_label: '完成首次联系并记录客户真实反馈',
        queue_category: 'new',
        lead: { id: 501, business_name: '示例商家', contact_name: '负责人', phone: '(555) 010-2026', industry: '餐饮', city: 'San Francisco', state: 'CA', status: 'new', do_not_contact: false, is_blacklisted: false },
      }],
    };
    else if (path.endsWith('/sales-leads/recovery/my-alerts')) data = { items: [] };
    else if (path.endsWith('/sales-leads/dashboard/performance')) data = { items: [] };
    else if (path.endsWith('/ringcentral/status')) data = { configured: false, connected: false };
    else if (path.includes('/app-config')) data = { items: {} };
    else if (path.includes('/entities/')) data = { items: [], total: 0 };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
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

test('销售知识库采用搜索优先三栏布局并支持短版与完整复制', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  await mockSalesApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${baseUrl}/sales-knowledge`);

  await expect(page.getByRole('heading', { name: '销售知识库' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: '知识分类' })).toBeVisible();
  await page.getByRole('button', { name: /客户说太贵如何回复/ }).click();
  await expect(page.getByText('电话短版')).toBeVisible();
  await expect(page.getByText('需要升级确认')).toBeVisible();
  await page.getByRole('button', { name: '复制短版话术' }).click();
  await expect(page.getByText('电话短版话术已复制')).toBeVisible();

  const search = page.getByRole('textbox', { name: '搜索销售知识库' });
  await search.fill('付款');
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(1);
  await expect(page.getByRole('button', { name: /客户怎么付款/ })).toBeVisible();

  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/sales-knowledge-v4-local.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: '销售知识库' })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test('销售今日工作台内嵌真实知识助手并支持收起与展开', async ({ page }) => {
  await mockSalesApi(page);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(`${baseUrl}/sales-workbench`);

  const assistant = page.getByRole('complementary', { name: '销售知识助手' });
  await expect(assistant.getByText('通话知识助手')).toBeVisible();
  await assistant.getByRole('button', { name: '太贵' }).click();
  await expect(assistant.getByRole('heading', { name: '客户说太贵如何回复？' })).toBeVisible();
  await assistant.getByRole('button', { name: '收起知识助手' }).click();
  await expect(assistant.getByRole('button', { name: '展开知识助手' })).toBeVisible();
  await assistant.getByRole('button', { name: '展开知识助手' }).click();
  await expect(assistant.getByText('通话知识助手')).toBeVisible();

  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/sales-workbench-knowledge-assistant-local.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('complementary', { name: '销售知识助手' })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
