import { expect, test } from '@playwright/test';
import { base, screenshots, day, employee, fixture, open, notes, save, key } from './fixtures/sales-workbench';

for (const width of [390, 1440]) {
  test(`${width}px 拨打时不用标记门店，纠错按需打开`, async ({ page }) => {
    await fixture(page);
    let verificationReads = 0;
    await page.route('**/api/v1/prospect-verification/lead/501', route => {
      expect(route.request().method()).toBe('GET');
      verificationReads++;
      return route.fulfill({ json: { entity_kind:'lead', entity_id:501, can_edit:true,
        prospect_quality:{ revision:0, status:'pending', corrected_fields:{chinese_service:'unknown'} },
        effective_fields:{}, prospect_source:{}, history:[] } });
    });
    await open(page, width);
    await expect(page.getByRole('region', { name:'门店标记' })).toHaveCount(0);
    expect(verificationReads).toBe(0);
    await page.getByRole('button', {name:'更多客户操作'}).click();
    await page.getByRole('menuitem', {name:'门店资料纠错'}).click();
    const correction = page.getByRole('dialog', {name:'门店资料纠错'});
    await expect(correction.getByLabel('首拨核验结果')).toBeEnabled();
    await page.keyboard.press('Escape');
    await expect(correction).toHaveCount(0);
    expect(verificationReads).toBe(1);
    await expect(notes(page)).toBeEditable();
  });
}

for (const width of [390, 1440]) {
  test(`切换、刷新及离开路由恢复正确客户的本地草稿（${width}）`, async ({ page }) => {
    const data = await fixture(page);
    await open(page, width);
    await notes(page).fill('甲商家1尚未提交的沟通');
    await page.getByRole('button', { name: '下一位客户', exact: true }).click();
    await notes(page).fill('甲商家2尚未提交的沟通');
    await expect(page.getByRole('status').filter({ hasText: '草稿已暂存' })).toBeVisible();
    if (screenshots) {
      await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
      await page.screenshot({ path: `${screenshots}/workbench-draft-local-${width}.png` });
      if (width === 1440) {
        await page.setViewportSize({ width: 1093, height: 824 });
        await page.screenshot({ path: `${screenshots}/workbench-draft-local-1093.png` });
        await page.setViewportSize({ width, height: 1000 });
      }
    }
    await page.reload();
    await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
    await expect(notes(page)).toHaveValue('甲商家2尚未提交的沟通');
    await expect(page.getByRole('status').filter({ hasText: '已恢复草稿' })).toBeVisible();
    if (width < 768) { await page.getByRole('button', { name: '打开销售中心功能菜单' }).click(); await page.getByRole('dialog').getByRole('button', { name: '知识库', exact: true }).click(); }
    else await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '知识库', exact: true }).click();
    await expect(page).toHaveURL(/sales-knowledge/);
    if (width < 768) { await page.getByRole('button', { name: '打开销售中心功能菜单' }).click(); await page.getByRole('dialog').getByRole('button', { name: '今日拨打', exact: true }).click(); }
    else await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '今日拨打', exact: true }).click();
    await expect(notes(page)).toHaveValue('甲商家2尚未提交的沟通');
    await page.getByRole('button', { name: '上一位客户', exact: true }).click();
    await expect(notes(page)).toHaveValue('甲商家1尚未提交的沟通');
    expect(data.writes).toEqual([]);
    await expect(page.getByRole('progressbar', { name: '任务完成进度' })).toHaveAttribute('aria-valuenow', '0');
  });
}

test('登录用户、销售与lead分别隔离，task编号相同也不会串稿', async ({ page }) => {
  const data = await fixture(page, { user: { ...employee, id: 1, role: 'sales_manager' } });
  await open(page);
  await notes(page).fill('主管1为销售甲商家1记录的草稿');
  await page.getByRole('combobox', { name: '选择销售', exact: true }).selectOption('28');
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('主管1为销售乙的草稿');
  await page.getByRole('combobox', { name: '选择销售', exact: true }).selectOption('27');
  await expect(notes(page)).toHaveValue('主管1为销售甲商家1记录的草稿');
  data.changeLead(777);
  await page.reload();
  await expect(page.getByRole('heading', { name: '重新分配后的商家', exact: true })).toBeVisible();
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('主管1为新lead777的草稿');
  await data.setUser({ ...employee, id: 40, role: 'sales_manager' });
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes).toEqual([]);
});

test('合法旧版草稿保留并迁移，超过一天仍须显式保存或丢弃', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(date => sessionStorage.setItem(`t24:sales-call-draft:v1:27:27:${date}:901`, JSON.stringify({ updatedAt: Date.now() - 3 * 86400000, values: { outcome: 'callback', notes: '三天前尚未提交的约定', nextFollowUpAt: '2026-10-15T10:30' } })), day());
  await open(page);
  await expect(notes(page)).toHaveValue('三天前尚未提交的约定');
  await expect(page.getByRole('status').filter({ hasText: '已恢复草稿' })).toBeVisible();
  expect(await page.evaluate(key => Boolean(sessionStorage.getItem(key)), key())).toBe(true);
  expect(data.writes).toEqual([]);
});

for (const raw of ['{broken', JSON.stringify({ version: 2, updatedAt: Date.now(), values: { outcome: 'interested', notes: { injected: 'invalid' }, nextFollowUpAt: '' } })]) {
  test(`损坏草稿不会崩溃、自动提交或删除原证据：${raw.slice(0, 15)}`, async ({ page }) => {
    const data = await fixture(page);
    await page.addInitScript(({ key, raw }) => sessionStorage.setItem(key, raw), { key: key(), raw });
    await open(page);
    await expect(notes(page)).toHaveValue('');
    await expect(page.getByRole('alert').filter({ hasText: '暂存草稿无法读取' })).toBeVisible();
    expect(await page.evaluate(key => sessionStorage.getItem(key), key())).toBe(raw);
    expect(data.writes).toEqual([]);
  });
}

test('浏览器暂存拒绝时明确提示风险，切换仍保留内存且成功保存不被存储错误误报', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    const remove = Storage.prototype.removeItem;
    Storage.prototype.getItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return get.call(this, key); };
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await open(page, 390);
  await notes(page).fill('仅在当前页面保留');
  await expect(page.getByRole('status').filter({ hasText: '本次页面保留' })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: '刷新会丢失' })).toBeVisible();
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await page.getByRole('button', { name: '上一位客户', exact: true }).click();
  await expect(notes(page)).toHaveValue('仅在当前页面保留');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  await expect(page.getByRole('status', { name: '上次保存结果' })).toContainText('已保存');
  expect(data.writes).toHaveLength(1);
  await expect(page.getByText('保存失败，记录已保留，请重试', { exact: true })).toHaveCount(0);
});

test('丢弃草稿必须确认，取消不丢失且只清除当前商家', async ({ page }) => {
  const data = await fixture(page);
  await open(page, 390);
  await notes(page).fill('甲商家1待保存');
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await notes(page).fill('甲商家2待保存');
  await page.getByRole('button', { name: '上一位客户', exact: true }).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await expect(notes(page)).toHaveValue('甲商家1待保存');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await expect(notes(page)).toHaveValue('');
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await expect(notes(page)).toHaveValue('甲商家2待保存');
  expect(data.writes).toEqual([]);
});

test('显式退出会清除内存兜底，同账号重新登录也不会恢复已退出页面的内存草稿', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    Storage.prototype.getItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return get.call(this, key); };
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
  });
  await open(page);
  await notes(page).fill('退出后不得恢复的内存草稿');
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole('textbox', { name: '用户名或邮箱', exact: true }).fill('sales@example.test');
  await page.getByLabel('密码', { exact: true }).fill('mock-password-only');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByRole('navigation', { name: '销售中心导航' }).getByRole('link', { name: '今日拨打', exact: true }).click();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes.filter(write => /\/result$|\/prepare/.test(write.path))).toEqual([]);
});

test('浏览器拒绝删除但允许读写时，成功保存和确认丢弃后都不会再生旧草稿', async ({ page }) => {
  const data = await fixture(page);
  await page.addInitScript(() => {
    const remove = Storage.prototype.removeItem;
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await open(page);
  await notes(page).fill('删除失败也不应再生');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '丢弃草稿', exact: true }).click();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await notes(page).fill('已成功提交不可再生');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect.poll(() => page.evaluate(key => JSON.parse(sessionStorage.getItem(key) || '{}').cleared === true, key())).toBe(true);
  await page.getByRole('complementary', {name:'今日客户队列'}).getByRole('button',{name:'全部',exact:true}).click();
  await page.locator('[data-lead-id="501"]').click();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  expect(data.writes).toHaveLength(1);
});

test('保存已成功但浏览器删除和覆写都拒绝时，明确警示而不误报失败或重复提交', async ({ page }) => {
  const data = await fixture(page);
  await open(page);
  await notes(page).fill('业务保存成功但浏览器清除失败');
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await page.evaluate(() => {
    const set = Storage.prototype.setItem;
    const remove = Storage.prototype.removeItem;
    Storage.prototype.setItem = function(key, value) { if (key.startsWith('t24:sales-call-draft:')) throw new DOMException('Blocked', 'SecurityError'); return set.call(this, key, value); };
    Storage.prototype.removeItem = function(key) { if (key.startsWith('t24:sales-call-draft:')) throw new DOMException('Blocked', 'SecurityError'); return remove.call(this, key); };
  });
  await save(page).click();
  await expect(page.getByText('记录已保存；浏览器暂存无法清除，刷新可能恢复旧草稿，请勿重复提交', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  await expect(page.getByText('保存失败，记录已保留，请重试', { exact: true })).toHaveCount(0);
  await page.getByRole('complementary', {name:'今日客户队列'}).getByRole('button',{name:'全部',exact:true}).click();
  await page.locator('[data-lead-id="501"]').click();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  await page.reload();
  await expect(notes(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  expect(data.writes).toHaveLength(1);
});

test('保存失败保留，成功后下一位与回访入口对应已保存的lead且不生成重复任务', async ({ page }) => {
  const data = await fixture(page, { failFirstSave: true });
  await open(page, 390);
  await page.getByRole('button', { name: '待回访', exact: true }).click();
  await notes(page).fill('约定下周回电');
  await page.getByLabel(/^下次跟进/).fill('2026-10-15T10:30');
  await save(page).click();
  await expect(page.getByRole('alert').filter({ hasText: '保存失败，记录已保留' })).toBeVisible();
  await page.reload();
  await expect(notes(page)).toHaveValue('约定下周回电');
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2', exact: true })).toBeVisible();
  const receipt = page.getByRole('status', { name: '上次保存结果' });
  await expect(receipt).toContainText('已保存 · 甲商家1');
  if (screenshots) {
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `${screenshots}/workbench-save-local-390.png` });
  }
  expect(await page.evaluate(key => sessionStorage.getItem(key), key())).toBeNull();
  await page.route(`${base}/sales-leads?lead_id=501&action=followup&returnTo=*`, route => route.fulfill({ contentType: 'text/html', body: '<title>本地跟进入口</title>' }));
  await receipt.getByRole('button', { name: '查看跟进', exact: true }).click();
  await expect(page).toHaveURL(`${base}/sales-leads?lead_id=501&action=followup&returnTo=${encodeURIComponent('/sales-workbench?sales_employee_id=27')}`);
  expect(data.writes.map(write => write.path)).toEqual(['/api/v1/sales-leads/workbench/tasks/901/result', '/api/v1/sales-leads/workbench/tasks/901/result']);
});

test('销售保存意向后看到主管踢单提示，打开成交登记不重复写入', async ({ page }) => {
  const data = await fixture(page);
  await open(page);
  await page.getByRole('button', { name: '有意向', exact: true }).click();
  await notes(page).fill('已讨论服务范围');
  await page.getByLabel(/^下次跟进/).fill('2026-10-15T10:30');
  await save(page).click();
  const receipt = page.getByRole('status', { name: '上次保存结果' });
  await expect(receipt).toContainText('甲商家1');
  if (screenshots) {
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `${screenshots}/workbench-save-local-1440.png` });
  }
  await expect(receipt).toContainText('主管和老板可在「意向踢单」查看跟进');
  await receipt.getByRole('button', { name: '登记成交', exact: true }).click();
  await expect(page.getByRole('dialog', { name: /登记成交/ })).toBeVisible();
  expect(data.writes).toHaveLength(1);
  expect(data.writes[0].body).toMatchObject({ outcome: 'interested', notes: '已讨论服务范围', next_follow_up_at: '2026-10-15T02:30:00.000Z' });
});

test('保存已经成功而队列刷新失败时不会误报保存失败或允许重复完成', async ({ page }) => {
  const data = await fixture(page, { failReadAfterSave: true });
  await open(page);
  await page.getByRole('button', { name: '未接通', exact: true }).click();
  await save(page).click();
  await expect(page.getByRole('status', { name: '上次保存结果' })).toContainText('已保存');
  await expect(page.getByRole('alert').filter({ hasText: '今日任务暂时无法更新' })).toBeVisible();
  await page.getByRole('complementary', {name:'今日客户队列'}).getByRole('button',{name:'全部',exact:true}).click();
  await page.locator('[data-lead-id="501"]').click();
  await expect(save(page)).toBeDisabled();
  await expect(notes(page)).toHaveValue('');
  expect(data.writes).toHaveLength(1);
});

test('禁联或转客户的历史草稿不恢复，也没有报价或重复结果入口', async ({ page }) => {
  const data = await fixture(page, { protected: true });
  await page.addInitScript(key => sessionStorage.setItem(key, JSON.stringify({ version: 2, updatedAt: Date.now(), values: { outcome: 'interested', notes: '应保留但不能恢复的草稿', nextFollowUpAt: '' } })), key());
  await open(page);
  await expect(notes(page)).toHaveValue('');
  await expect(notes(page)).toBeDisabled();
  await expect(save(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: '拨打电话', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '下一位客户', exact: true }).click();
  await expect(notes(page)).toBeDisabled();
  await expect(page.getByRole('button', { name: '准备报价', exact: true })).toHaveCount(0);
  expect(data.writes).toEqual([]);
});

test('空任务与读取失败分别呈现，只有明确操作才能生成任务', async ({ page }) => {
  const data = await fixture(page, { empty: true, failRead: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '今日任务暂不可用' })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成今日任务', exact: true })).toHaveCount(0);
  data.recover();
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('heading', { name: '当前队列暂无任务', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成今日任务', exact: true })).toBeEnabled();
  expect(data.writes).toEqual([]);
  expect(data.reads.some(path => /dashboard\/management|merchant-pool\/stats/.test(path))).toBe(false);
});

test('主管仍默认只读团队，明确打开个人任务后使用实际销售草稿范围', async ({ page }) => {
  const data = await fixture(page, { user: { ...employee, id: 1, role: 'sales_manager' } });
  await page.goto(`${base}/sales-workbench`);
  await expect(page.getByRole('heading', { name: '团队今日任务', exact: true })).toBeVisible();
  await expect(notes(page)).toHaveCount(0);
  await page.getByRole('button', { name: '查看任务：模拟销售乙', exact: true }).click();
  await expect(page.getByRole('heading', { name: '乙商家1', exact: true })).toBeVisible();
  await notes(page).fill('仅主管1和销售28的客户范围');
  expect(data.writes).toEqual([]);
});

for (const width of [390, 1440]) {
  test(`本人配额外商家可开始联系、返回后只选未接即保存（${width}）`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const data = await fixture(page, { manualLead: true });
    const dialUrl = 'https://app.ringcentral.com/r/call?number=12025550123';
    await page.route('https://app.ringcentral.com/**', route => route.fulfill({ contentType: 'text/html', body: '<p>本地拦截拨号器</p>' }));
    await page.goto(`${base}/sales-workbench?lead_id=503&sales_employee_id=27`);
    const start = page.getByRole('button', { name: '开始联系 · 名下待联系商家', exact: true });
    await expect(start).toBeVisible();
    expect(data.writes).toEqual([]);
    await start.click();
    await expect(page.getByRole('heading', { name: '名下待联系商家', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '拨打电话', exact: true }).click();
    await expect(page).toHaveURL(dialUrl);
    await page.goBack();
    const surface = page.getByTestId(width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
    await expect(surface.getByRole('heading', { name: '名下待联系商家', exact: true })).toBeVisible();
    expect(data.writes.map(item => item.path)).toEqual([
      '/api/v1/sales-leads/workbench/manual-task/503', '/api/v1/sales-leads/workbench/tasks/903/dial-started',
    ]);
    await surface.getByRole('button', { name: '未接通', exact: true }).click();
    await surface.getByRole('button', { name: '保存并下一位', exact: true }).click();
    await expect(surface.getByLabel('上次保存结果')).toContainText('名下待联系商家');
    expect(data.writes.at(-1)?.path).toBe('/api/v1/sales-leads/workbench/tasks/903/result');
    expect(data.writes.at(-1)?.body.outcome).toBe('no_answer');
    expect(data.writes).toHaveLength(3);
  });
}

for (const width of [390, 1440]) {
  test(`销售可自行选择行业补单，保护回访与草稿（${width}）`, async ({ page }) => {
    const { writes, reads } = await fixture(page, { industryChoice: true });
    await open(page, width);
    await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
    await page.getByRole('button', { name: '下一位客户', exact: true }).click();
    await expect(page.getByRole('heading', { name: '甲商家1' })).toBeVisible();
    await notes(page).fill('店主的沟通草稿');
    const choices = page.getByRole('group', { name: '拨打行业' });
    await choices.getByRole('button', { name: '餐厅', exact: true }).click();
    await expect(page.getByRole('heading', { name: '当前条件下没有餐厅任务' })).toBeVisible();
    await expect(page.getByText('到期回访（1）')).toBeVisible();
    expect(writes.filter(row => row.path.includes('/workbench/'))).toHaveLength(0);
    await page.getByRole('button', { name:'领取名单', exact:true }).click();
    const regions = page.getByRole('group', { name: '领取时区' });
    await expect(regions.getByRole('button', { name:'山地' })).toContainText('09:30 / 10:30');
    await regions.getByRole('button', { name:'山地' }).click();
    await page.getByLabel('首拨名单目标数量').selectOption('1');
    expect(writes.filter(row => row.path.includes('/workbench/'))).toHaveLength(0);
    await page.getByRole('button', { name: '领取餐厅名单' }).click();
    await expect(page.getByRole('heading', { name: '新餐厅' })).toBeVisible();
    expect(writes.filter(row => row.path.includes('/workbench/'))).toEqual([
      { path: '/api/v1/sales-leads/workbench/prepare-industry', body: { preserve_task_ids: [901] } },
    ]);
    // A different browsing filter must not lose the precise receipt or restrict its target.
    await choices.getByRole('button', { name:'美业', exact:true }).click();
    await page.getByRole('button', { name: '查看任务 · 新餐厅', exact:true }).click();
    await expect(page.getByRole('heading', { name:'新餐厅', exact:true })).toBeVisible();
    const progress = page.getByRole('progressbar', { name: '任务完成进度' });
    await expect(progress).toHaveAttribute('aria-valuemax', '3');
    await expect(progress).toHaveAttribute('aria-valuenow', '0');
    await page.getByRole('button', { name: '话术', exact: true }).click();
    await expect.poll(() => reads.some(path => path.includes('/sales-knowledge/articles?product_scope=managed_service'))).toBe(true);
    await page.getByRole('dialog').getByRole('button', { name: '关闭' }).click();
    await choices.getByRole('button', { name:'餐厅', exact:true }).click();
    await page.getByText('到期回访（1）').click();
    await page.getByRole('button', {name: /甲商家2.*美业/}).click();
    await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
    await expect(choices.getByRole('button', { name: '全部行业', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: '下一位客户', exact: true }).click();
    await expect(notes(page)).toHaveValue('店主的沟通草稿');
  });
}


for (const width of [390, 1440]) {
  test(`分配回执定位名下商家，非当地时段可找回并明确开始联系（${width}）`, async ({ page }) => {
    const { writes } = await fixture(page, { manualLead: true });
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`${base}/sales-workbench?sales_employee_id=27&scope=assigned&lead_id=503`);
    const list = page.getByRole('region', { name: '销售名单' });
    await expect(list.getByRole('button', {name:'名下待联系商家', exact:true})).toBeVisible();
    await expect(list.getByText(/当地 21:30.*10:00 起建议联系/)).toBeVisible();
    await expect(list.getByRole('listitem')).toHaveCount(1);
    if (screenshots) await page.screenshot({ path: `${screenshots}/owned-queue-${width}.png` });
    await list.getByRole('button', {name:/现在可拨/}).click();
    await expect(list.getByText('目前没有符合当地时段及联系条件的商家')).toBeVisible();
    await list.getByRole('button', {name:'查看名下商家', exact:true}).click();
    await expect(list.getByRole('listitem')).toHaveCount(3);
    expect(writes).toEqual([]);
    await list.getByRole('listitem').filter({hasText:'名下待联系商家'}).getByRole('button', {name:'开始联系'}).click();
    await expect(page.getByRole('heading', {name:'名下待联系商家', exact:true})).toBeVisible();
    expect(writes.map(w => w.path)).toEqual(['/api/v1/sales-leads/workbench/manual-task/503']);
  });
}

test('主管在分配回执只能查看名下商家，不能代为开始联系或回退到其他员工', async ({ page }) => {
  const { writes } = await fixture(page, { user: { ...employee, id: 1, role: 'sales_manager' }, manualLead: true });
  const url = base + '/sales-workbench?scope=assigned&lead_id=503&sales_employee_id=';
  await page.goto(url + '27');
  const list = page.getByRole('region', { name:'销售名单' });
  await expect(list.getByRole('button', { name:'名下待联系商家', exact: true })).toBeVisible();
  await expect(list.getByRole('button', { name:'开始联系', exact: true })).toHaveCount(0);
  await page.goto(url + '999');
  await expect(page.getByText('该销售不在当前可查看范围，请选择可访问的销售人员。')).toBeVisible();
  await expect(list).toHaveCount(0);
  expect(writes).toEqual([]);
});


for (const editing of ['空闲', '写草稿', '已拨号待记录']) {
  test(`领取后按销售当前操作决定是否自动定位（${editing}）`, async ({ page }) => {
    const data = await fixture(page, { industryChoice: true });
    if (editing === '已拨号待记录') await page.addInitScript(date => {
      sessionStorage.setItem('t24:sales-workbench:pending-dial:v2:27', JSON.stringify({
        userId:27, salesId:27, date, taskId:902, leadId:502, createdAt:Date.now(),
      }));
    }, day());
    await open(page, 390);
    await expect(page.getByRole('heading', {name:'甲商家2', exact:true})).toBeVisible();
    if (editing === '写草稿') await notes(page).fill('当前正在记录，领取不要切换');
    await page.getByRole('button', {name:'领取名单', exact:true}).click();
    await page.getByRole('group', {name:'领取时区'}).getByRole('button', {name:'山地'}).click();
    await page.getByLabel('首拨名单目标数量').selectOption('1');
    await page.getByRole('button', {name:'领取餐厅名单', exact:true}).click();
    await expect(page.getByRole('button', {name:'查看任务 · 新餐厅'})).toBeVisible();
    await expect(page.getByRole('heading', {name: editing === '空闲' ? '新餐厅' : '甲商家2', exact:true})).toBeVisible();
    if (editing === '写草稿') await expect(notes(page)).toHaveValue('当前正在记录，领取不要切换');
    expect(data.writes.map(w => w.path)).toEqual(['/api/v1/sales-leads/workbench/prepare-industry']);
  });
}

test('历史分配回执读取当前归属，打开跨北京零点也能继续查看', async ({ page }) => {
  await page.clock.install({time:new Date('2026-11-17T23:59:55+08:00')});
  const { reads, writes } = await fixture(page, {manualLead:true});
  await page.goto(base + '/sales-workbench?scope=assigned&lead_id=503&sales_employee_id=27&target_date=2025-10-21');
  const list = page.getByRole('region', {name:'销售名单'});
  await expect(list.getByRole('button', {name:'名下待联系商家', exact:true})).toBeVisible();
  await expect.poll(() => reads.some(r => r.includes('/workbench/owned?target_date=2026-11-17'))).toBe(true);
  await page.clock.fastForward(10_000);
  await expect.poll(() => reads.some(r => r.includes('/workbench/owned?target_date=2026-11-18'))).toBe(true);
  await expect(list.getByRole('button', {name:'名下待联系商家', exact:true})).toBeVisible();
  expect(reads.some(r => r.includes('target_date=2025-10-21'))).toBe(false);
  expect(writes).toEqual([]);
});

test('跨零点编辑中的历史任务保留草稿，当前归属仍能打开', async ({page}) => {
  await page.clock.install({time:new Date('2026-11-17T23:59:55+08:00')});
  await fixture(page);
  await open(page);
  await notes(page).fill('保留在昨天的任务草稿');
  await page.clock.fastForward(10_000);
  await expect(page.getByRole('heading', {name:'拨打记录',exact:true})).toBeVisible();
  await expect(notes(page)).toHaveValue('保留在昨天的任务草稿');
  await page.getByRole('button', {name:/已分配给我/}).click();
  await expect(page.getByRole('region', {name:'销售名单'}).getByRole('listitem')).toHaveCount(2);
});

test('今日待拨只列出待拨，全部任务能单独查看已记录商家', async ({page}) => {
  await fixture(page, {completedFirst:true});
  await open(page);
  const pending = page.getByRole('button', {name:'今日待拨 1',exact:true});
  await expect(pending).toHaveAttribute('aria-pressed','true');
  const queue = page.getByRole('complementary', {name:'今日客户队列'});
  await expect(queue.locator('[data-lead-id]')).toHaveCount(1);
  await queue.getByRole('button',{name:'全部',exact:true}).click();
  await expect(queue.locator('[data-lead-id]')).toHaveCount(2);
  await expect(pending).toHaveAttribute('aria-pressed','false');
  await pending.click();
  await expect(queue.locator('[data-lead-id]')).toHaveCount(1);
});

test('选择补至100家，部分领取后定位第一家并可查看第二家', async ({page}) => {
  const {writes} = await fixture(page,{industryChoice:true, multiClaim:true});
  await open(page, page.viewportSize()?.width ?? 1440);
  await page.getByRole('button', {name:'领取名单',exact:true}).click();
  await page.getByRole('group',{name:'领取时区'}).getByRole('button',{name:'山地'}).click();
  await page.getByLabel('首拨名单目标数量').selectOption('100');
  await page.getByRole('button',{name:'领取餐厅名单',exact:true}).click();
  await expect(page.getByRole('heading',{name:'新餐厅',exact:true})).toBeVisible();
  const receipt = page.locator('.sw-claim-receipt').filter({hasText:'已补充 2 家餐厅'});
  await receipt.getByRole('button',{name:'第二家餐厅',exact:true}).click();
  await expect(page.getByRole('heading',{name:'第二家餐厅',exact:true})).toBeVisible();
  expect(writes.map(w => w.path)).toEqual(['/api/v1/sales-leads/workbench/prepare-industry']);
});
