import { expect, test, type Page } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5191';
const screenshotDir = process.env.T24_UI_SCREENSHOT_DIR;
const priceAnswer = '我理解您希望控制费用。请先确认目前最需要解决的问题，我们会按真实需求说明合适的服务范围。';
const articles = [
  { id: 1, category: '套餐与报价', title: '客户说太贵如何回复？', customer_question: '客户觉得报价太贵，销售怎么推进？', standard_answer: priceAnswer, action_steps: ['确认真实需求', '按需求说明服务范围'], escalation_rule: '特殊折扣必须先由销售主管确认。', related_links: [], tags: ['价格'], status: 'published', is_sensitive: true, sort_order: 20 },
  { id: 2, category: '销售准备与开场', title: '首次联系如何开场？', customer_question: '第一次联系商家怎么开场？', standard_answer: '请先确认商家负责人，再介绍联系目的。', action_steps: [], related_links: [], tags: ['开场'], status: 'published', is_sensitive: false, sort_order: 30 },
  { id: 3, category: '特殊交接说明', title: '特殊交接待发布草稿', customer_question: '交接如何确认？', standard_answer: '由主管确认交接范围后发布。', action_steps: [], related_links: [], tags: [], status: 'draft', is_sensitive: false, sort_order: 40 },
];

type Write = { path: string; method: string; data: Record<string, unknown>; query: string };

async function mockKnowledge(page: Page, role: 'sales' | 'sales_manager' = 'sales', failFirstQuestion = false) {
  const employee = { id: 27, name: '知识库布局测试', role, status: 'active' };
  const writes: Write[] = [];
  const reads: string[] = [];
  let questionAttempt = 0;
  let resolved = false;
  await page.addInitScript(({ emp }) => {
    localStorage.setItem('emp_auth_token', 'knowledge-layout-fixture');
    localStorage.setItem('token', 'knowledge-layout-fixture');
    localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === 'GET') reads.push(path + url.search);
    else writes.push({ path, method: request.method(), data: request.postDataJSON() || {}, query: url.search });
    let data: unknown = {};
    if (path.endsWith('/emp-auth/me')) data = employee;
    else if (path.endsWith('/sales-knowledge/articles') && request.method() === 'GET') {
      const query = url.searchParams.get('query') || '';
      const category = url.searchParams.get('category');
      const includeAll = url.searchParams.get('include_all') === 'true';
      data = { items: articles.filter(article => (includeAll || article.status === 'published') && (!category || article.category === category) && (!query || `${article.title} ${article.customer_question} ${article.standard_answer}`.includes(query))), categories: [...new Set(articles.map(article => article.category))] };
    } else if (path.endsWith('/sales-knowledge/questions') && request.method() === 'GET') {
      data = { items: resolved ? [] : [{ id: 11, question: '等待主管补充的实际问题', context: '通话中客户要求特殊折扣', status: 'open', submitted_by_name: '测试销售', created_at: '2026-10-10T09:00:00' }] };
    } else if (path.endsWith('/sales-knowledge/questions') && request.method() === 'POST') {
      questionAttempt += 1;
      if (failFirstQuestion && questionAttempt === 1) {
        await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: '测试提交失败，请重试' }) });
        return;
      }
      data = { id: 99, status: 'open' };
    } else if (path.endsWith('/questions/11/resolve')) {
      resolved = true;
      data = { id: 11, status: 'resolved' };
    } else if (path.endsWith('/sales-knowledge/articles') && request.method() === 'POST') data = { id: 100 };
    else if (path.endsWith('/sales-leads/notifications')) data = { count: 0, items: [] };
    else if (path.endsWith('/system-options')) data = { items: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return { writes, reads };
}

async function noOverflow(page: Page) {
  const metrics = await page.evaluate(() => ({ window: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  expect(metrics.document).toBeLessThanOrEqual(metrics.window);
  expect(metrics.body).toBeLessThanOrEqual(metrics.window);
}

for (const width of [1093, 1440]) {
  test(`知识库 ${width}px 两栏清晰且电话/完整答复复制保留真实内容`, async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
    const api = await mockKnowledge(page);
    await page.setViewportSize({ width, height: 824 });
    await page.goto(`${baseUrl}/sales-knowledge`);
    await expect(page.getByRole('heading', { name: '销售知识库' })).toBeVisible();
    await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(2);
    const list = await page.getByRole('region', { name: '知识卡列表' }).boundingBox();
    const detail = await page.locator('.knowledge-v4-detail').boundingBox();
    expect(list && detail).toBeTruthy();
    expect(detail!.x).toBeGreaterThan(list!.x + list!.width);
    expect(Math.abs(detail!.y - list!.y)).toBeLessThan(2);
    await expect(page.getByRole('tab', { name: '电话话术' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('特殊折扣必须先由销售主管确认。')).toBeVisible();
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/knowledge-approved-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: '复制短版话术' }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(priceAnswer);
    await page.getByRole('tab', { name: '完整答复', exact: true }).click();
    await page.getByRole('button', { name: '复制完整答复' }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(`客户说太贵如何回复？\n\n标准答复：\n${priceAnswer}\n\n建议步骤：\n1. 确认真实需求\n2. 按需求说明服务范围`);
    await page.getByRole('tab', { name: '完整答复', exact: true }).press('ArrowLeft');
    await expect(page.getByRole('tab', { name: '电话话术' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('button', { name: /首次联系如何开场/ }).click();
    await expect(page.getByRole('tab', { name: '电话话术' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('button', { name: '新建知识卡' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '编辑知识卡' })).toHaveCount(0);
    expect(api.writes).toHaveLength(0);
    expect(api.reads.some(path => path.includes('/sales-knowledge/questions'))).toBe(false);
    await noOverflow(page);
  });
}

test('800px 窄桌面正文仍可访问，列表和详情堆叠不被误当手机隐藏', async ({ page }) => {
  await mockKnowledge(page);
  await page.setViewportSize({ width: 800, height: 800 });
  await page.goto(`${baseUrl}/sales-knowledge`);
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(2);
  await page.getByRole('button', { name: /首次联系如何开场/ }).click();
  await expect(page.locator('.knowledge-v4-detail')).toBeVisible();
  await expect(page.getByRole('button', { name: '复制短版话术' })).toBeVisible();
  await noOverflow(page);
});

test('无结果提交保留搜索原话和分类，失败及取消保留已补充场景', async ({ page }) => {
  const api = await mockKnowledge(page, 'sales', true);
  await page.goto(`${baseUrl}/sales-knowledge`);
  await page.getByRole('complementary', { name: '知识分类' }).getByRole('button', { name: '套餐与报价', exact: true }).click();
  const original = '客户问异地套餐怎么使用';
  await page.getByRole('textbox', { name: '搜索销售知识库' }).fill(original);
  await page.getByRole('button', { name: '提交这个问题' }).click();
  const dialog = page.getByRole('dialog', { name: '提交销售新问题' });
  await expect(dialog.getByLabel('客户问了什么？')).toHaveValue(original);
  await expect(dialog.getByLabel('补充场景（可选）')).toHaveValue('知识分类：套餐与报价');
  await dialog.getByLabel('补充场景（可选）').fill('客户在异地，正在讨论套餐范围');
  await dialog.getByRole('button', { name: '提交问题', exact: true }).click();
  await expect(dialog.getByRole('alert')).toHaveText('测试提交失败，请重试');
  await expect(dialog.getByLabel('客户问了什么？')).toHaveValue(original);
  await dialog.getByRole('button', { name: '取消' }).click();
  await page.getByRole('button', { name: '提交这个问题' }).click();
  await expect(dialog.getByLabel('补充场景（可选）')).toHaveValue('客户在异地，正在讨论套餐范围');
  await dialog.getByRole('button', { name: '提交问题', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.writes).toHaveLength(2);
  for (const write of api.writes) expect(write.data).toEqual({ question: original, context: '客户在异地，正在讨论套餐范围' });
});

test('主管真实分类、草稿保存与待解答问题处理入口完整', async ({ page }) => {
  const api = await mockKnowledge(page, 'sales_manager');
  await page.goto(`${baseUrl}/sales-knowledge`);
  await expect(page.getByRole('button', { name: /特殊交接待发布草稿/ })).toBeVisible();
  await page.getByRole('complementary', { name: '知识分类' }).getByRole('button', { name: '特殊交接说明', exact: true }).click();
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(1);
  expect(api.reads.some(path => path.includes('category=%E7%89%B9%E6%AE%8A%E4%BA%A4%E6%8E%A5%E8%AF%B4%E6%98%8E'))).toBe(true);
  await page.getByRole('button', { name: '新建知识卡' }).click();
  const editor = page.getByRole('dialog', { name: '新建知识卡' });
  await editor.getByLabel('新分类名称（选填）').fill('主管补充分类');
  await editor.getByLabel('标题', { exact: true }).fill('新客户咨询答复');
  await editor.getByLabel('标准答复', { exact: true }).fill('请按客户实际需求说明服务。');
  await editor.getByLabel('执行步骤（每行一条）').fill('确认需求\n记录客户反馈');
  await editor.getByLabel('保存后立即发布给销售查看').uncheck();
  await editor.getByRole('button', { name: '保存知识卡' }).click();
  await expect(editor).toHaveCount(0);
  const saved = api.writes.find(write => write.path.endsWith('/sales-knowledge/articles'));
  expect(saved?.method).toBe('POST');
  expect(saved?.query).toBe('?publish_now=false');
  expect(saved?.data).toMatchObject({ category: '主管补充分类', title: '新客户咨询答复', standard_answer: '请按客户实际需求说明服务。', action_steps: ['确认需求', '记录客户反馈'] });
  await page.locator('.sk-open-questions summary').click();
  await expect(page.getByText('等待主管补充的实际问题')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '标记已处理' }).click();
  await expect(page.locator('.sk-open-questions')).toHaveCount(0);
  expect(api.writes.at(-1)?.path).toBe('/api/v1/sales-knowledge/questions/11/resolve');
});

test('390px 手机分类可达，正文按需打开且复制控件和输入不缩水', async ({ page }) => {
  await mockKnowledge(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/sales-knowledge`);
  await expect(page.locator('.knowledge-v4-list-item')).toHaveCount(2);
  await noOverflow(page);
  await page.getByRole('button', { name: /客户说太贵如何回复/ }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet.getByRole('tab', { name: '电话话术' })).toBeVisible();
  await expect(sheet.getByText('特殊折扣必须先由销售主管确认。')).toBeVisible();
  await sheet.getByRole('tab', { name: '完整答复', exact: true }).click();
  await expect(sheet.getByRole('button', { name: '复制完整答复' })).toBeVisible();
  const target = await sheet.getByRole('button', { name: '复制完整答复' }).boundingBox();
  expect(target!.height).toBeGreaterThanOrEqual(44);
  await noOverflow(page);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/knowledge-approved-mobile.png` });
  await sheet.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('complementary', { name: '知识分类' }).getByRole('button', { name: '其他', exact: true }).click();
  await expect(page.getByRole('button', { name: '提交这个问题' })).toBeVisible();
  await page.getByRole('button', { name: '提交这个问题' }).click();
  const question = page.getByRole('dialog', { name: '提交销售新问题' });
  const size = await question.getByLabel('客户问了什么？').evaluate(element => parseFloat(getComputedStyle(element).fontSize));
  expect(size).toBeGreaterThanOrEqual(16);
});
