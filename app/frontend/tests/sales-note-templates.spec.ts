import { expect, test, type Page } from '@playwright/test';
import { fixture, notes, open, save, screenshots } from './fixtures/sales-workbench';

const group = (page: Page) => page.getByRole('group', { name: '本次沟通 可多选' });
const choice = (page: Page, name: string) => group(page).getByRole('button', { name, exact: true });
const note = (page: Page, label: string) => choice(page, '备注：' + label);
const gatekeeper = { id: 'gatekeeper', label: '前台／老板不在', text: '前台接听，老板不在。' };
const english = { id: 'english', label: '英文沟通', text: '对方讲英文，暂未能有效沟通。' };

async function expand(page: Page) {
  const more = page.getByRole('button', { name: /^更多选项/ });
  if (await more.count()) await more.click();
}

for (const width of [390, 1440]) {
  test(`兼容结果和备注可多选，恢复草稿后只产生一次提交（${width}）`, async ({ page }) => {
    const { writes } = await fixture(page);
    await open(page, width);
    await notes(page).fill('客户周二有空。');
    await choice(page, '有意向').click();
    await choice(page, '待回访').click();
    await choice(page, '已预约').click();
    await note(page, gatekeeper.label).click();
    await note(page, english.label).click();
    await page.getByLabel(/^下次跟进/).fill('2026-12-20T10:30');
    await page.reload();
    const expectedNotes = ['客户周二有空。', gatekeeper.text, english.text].join('\n');
    await expect(notes(page)).toHaveValue(expectedNotes);
    await expect(group(page).getByRole('button', { pressed: true })).toHaveCount(5);
    await expect(page.getByLabel(/^下次跟进/)).toHaveValue('2026-12-20T10:30');
    if (screenshots) {
      await group(page).evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
      await page.screenshot({ path: `${screenshots}/communication-choices-${width}.png` });
    }
    await save(page).click();
    await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
    expect(writes).toHaveLength(1);
    expect(writes[0].body).toMatchObject({ outcome: 'appointment', outcomes: ['interested', 'callback', 'appointment'],
      quick_notes: [gatekeeper, english], notes: expectedNotes });
    await expect(notes(page)).toHaveValue('');
    await expect(group(page).getByRole('button', { pressed: true })).toHaveCount(0);
  });

  test(`仅勾选普通沟通事实即可保存，并使用中性的已记录沟通（${width}）`, async ({ page }) => {
    const { writes } = await fixture(page);
    await open(page, width);
    await note(page, gatekeeper.label).click();
    await note(page, english.label).click();
    await expect(page.getByLabel(/^下次跟进/)).toHaveCount(0);
    await save(page).click();
    await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
    expect(writes).toHaveLength(1);
    expect(writes[0].body).toMatchObject({ outcome: 'recorded', outcomes: [], next_follow_up_at: null, quick_notes: [gatekeeper, english] });
  });
}

test('取消模板保留手工输入与编辑过的模板内容', async ({ page }) => {
  const { writes } = await fixture(page);
  await open(page, 390);
  await notes(page).fill(gatekeeper.text);
  await note(page, gatekeeper.label).click();
  await note(page, english.label).click();
  await note(page, gatekeeper.label).click();
  await expect(notes(page)).toHaveValue(gatekeeper.text + '\n' + english.text);
  await notes(page).fill('张店长：' + gatekeeper.text + '\n' + '暂未能有效沟通，下周约翻译。');
  await note(page, english.label).click();
  await expect(notes(page)).toHaveValue('张店长：' + gatekeeper.text + '\n暂未能有效沟通，下周约翻译。');
  await expect(group(page).getByRole('button', { pressed: true })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('禁联提醒需明确选择结果；互斥结果自动取消，禁联需亲自取消', async ({ page }) => {
  const { writes } = await fixture(page);
  await open(page, 390);
  await expand(page);
  await note(page, '要求不再联系').click();
  await save(page).click();
  await expect(page.getByRole('alert').filter({ hasText: '请明确选择本次结果' })).toBeVisible();
  expect(writes).toEqual([]);
  await choice(page, '有意向').click();
  await choice(page, '已预约').click();
  await choice(page, '未接通').click();
  await expect(choice(page, '有意向')).toHaveAttribute('aria-pressed', 'false');
  await expect(choice(page, '已预约')).toHaveAttribute('aria-pressed', 'false');
  await choice(page, '禁止再联系').click();
  await expect(choice(page, '未接通')).toBeDisabled();
  await expect(page.getByLabel(/^下次跟进/)).toHaveCount(0);
  await choice(page, '禁止再联系').click();
  await expect(choice(page, '未接通')).toBeEnabled();
  await choice(page, '禁止再联系').click();
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
  expect(writes[0].body).toMatchObject({ outcome: 'do_not_contact', outcomes: ['do_not_contact'] });
});

test('超过备注字数上限时保留手工原文和原有选项', async ({ page }) => {
  const { writes } = await fixture(page);
  await open(page);
  const previous = '中'.repeat(4000 - gatekeeper.text.length - 1);
  await notes(page).fill(previous);
  await note(page, gatekeeper.label).click();
  await note(page, english.label).click();
  await expect(notes(page)).toHaveValue(previous + '\n' + gatekeeper.text);
  await expect(note(page, english.label)).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('沟通内容最多 4000 字，请先删减后再选择备注')).toBeVisible();
  expect(writes).toEqual([]);
});

test('老板修改模板后，销售已选择的快捷备注仍按当时所见保存', async ({ page }) => {
  const { writes } = await fixture(page);
  let template = { id: 'special', label: '要一份介绍', text: '发中文资料。', enabled: true, industry: 'all', remind_do_not_contact: false };
  await page.route('**/api/v1/app-config/sales/quick-note-templates', route => route.fulfill({ json: { templates: [template], revision: 'a'.repeat(64) } }));
  await open(page, 390);
  await note(page, '要一份介绍').click();
  template = { ...template, text: '只发英文介绍。', label: '改名后' };
  await page.reload();
  await expect(note(page, '要一份介绍')).toHaveAttribute('aria-pressed', 'true');
  await save(page).click();
  await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
  expect(writes[0].body.quick_notes).toEqual([{ id: 'special', label: '要一份介绍', text: '发中文资料。' }]);
});

test('追加跟进重试保留同一个提交流水号和完整多选', async ({ page }) => {
  await fixture(page, { completedFirst: true });
  const attempts: Record<string, unknown>[] = [];
  await page.route('**/api/v1/sales-leads/501/follow-up', async route => {
    attempts.push(route.request().postDataJSON());
    await route.fulfill(attempts.length === 1 ? { status: 503, json: { detail: '模拟网络故障' } } : { json: { lead_id: 501 } });
  });
  const enter = async () => {
    const queue = page.getByRole('complementary', { name: '今日客户队列' });
    await queue.getByRole('button', { name: '全部', exact: true }).click();
    await queue.locator('[data-lead-id="501"]').click();
    await page.getByRole('button', { name: '更多客户操作' }).click();
    await page.getByRole('menuitem', { name: '追加跟进' }).click();
    return page.getByRole('dialog', { name: /追加跟进/ });
  };
  await open(page);
  const drawer = await enter();
  await drawer.getByRole('button', { name: '备注：英文沟通' }).click();
  await drawer.getByRole('button', { name: '保存跟进' }).click();
  await expect(drawer.getByRole('alert')).toHaveText('保存失败，记录已保留，请重试');
  await page.reload();
  await enter();
  await expect(drawer.getByRole('button', { name: '备注：英文沟通' })).toHaveAttribute('aria-pressed', 'true');
  await drawer.getByRole('button', { name: '保存跟进' }).click();
  await expect(drawer).toHaveCount(0);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].submission_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(attempts[1]).toEqual(attempts[0]);
});

test('320px 手机上多选区完整显示，保护名单不能误记', async ({ page }) => {
  const { writes } = await fixture(page, { protected: true });
  await open(page, 320);
  for (const button of await group(page).getByRole('button').all()) {
    await expect(button).toBeDisabled();
    const box = await button.boundingBox();
    expect(box?.width).toBeGreaterThan(0);
    expect(await button.evaluate(element => (element as HTMLElement).offsetHeight)).toBeGreaterThanOrEqual(44);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
  }
  await expect(save(page)).toBeDisabled();
  expect(writes).toEqual([]);
});

test('历史弹窗可读出多个结果与模板快照，并兼容旧记录', async ({ page }) => {
  await fixture(page);
  await page.route('**/api/v1/sales-leads/501/call-history', route => route.fulfill({ json: [
    { id: 91, outcome: 'appointment', outcome_label: '已预约', outcome_labels: ['有意向','待回访','已预约'],
      quick_notes: [gatekeeper], notes: '周二看演示。', called_at: '2026-11-17T01:15:00Z' },
    { id: 77, outcome: 'no_answer', outcome_label: '未接通', notes: '周二再联系。', called_at: '2026-11-10T03:00:00Z' },
  ] }));
  await open(page, 390);
  await page.getByRole('button', { name: '更多客户操作' }).click();
  await page.getByRole('menuitem', { name: '历史联系' }).click();
  const dialog = page.getByRole('dialog', { name: /历史联系记录/ });
  for (const text of ['有意向 · 待回访 · 已预约', gatekeeper.label, '周二看演示。', '未接通']) {
    await expect(dialog.getByText(text, { exact: true })).toBeVisible();
  }
});
