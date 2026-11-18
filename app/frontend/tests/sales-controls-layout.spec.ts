import { expect, test, type Locator, type Page } from '@playwright/test';

import { day, fixture, notes, open, save } from './fixtures/sales-workbench';

const outcomes = [
  { value: 'no_answer', label: '未接通', followUp: true },
  { value: 'callback', label: '待回访', followUp: true },
  { value: 'interested', label: '有意向', followUp: true },
  { value: 'appointment', label: '已预约', followUp: true },
  { value: 'not_now', label: '暂时不需要（60天后轮换）', followUp: false },
  { value: 'existing_provider', label: '已有服务商（90天后轮换）', followUp: false },
  { value: 'not_interested', label: '无意向', followUp: false },
  { value: 'do_not_contact', label: '禁止再联系', followUp: false },
];
const viewports = [
  { width: 1440, height: 900 },
  { width: 1093, height: 824 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
  { width: 320, height: 740 },
];

const longMerchantName = 'InternationalRestaurantAndHospitalityManagementCompany';
async function openLayout(page: Page, width: number, height: number) {
  const data = await fixture(page);
  await page.route('**/api/v1/sales-leads/workbench/today?*', route => {
    const items = [longMerchantName, '下一位合成商家'].map((business_name, index) => ({
      task_id: 901 + index, task_status: 'pending', priority: 'normal', queue_category: 'new',
      lead: { id: 501 + index, business_name, phone: '+12025550123', country: 'US', status: 'new',
        do_not_contact: false, is_blacklisted: false },
    }));
    return route.fulfill({ json: { salesperson: { id: 27, name: '模拟销售甲' }, target_date: day(),
      quota: 20, assigned_count: 2, completed_count: 0, remaining_count: 2, is_target_complete: false,
      categories: { unfinished: 2, callback: 0, interested: 0, appointment: 0, new: 2 },
      performance: { attempted: 0, connected: 0, interested: 0, appointments: 0, callbacks_due: 0, connection_rate: 0 }, items } });
  });
  await open(page, width);
  await page.setViewportSize({ width, height });
  await expect(page.getByRole('heading', { name: longMerchantName })).toBeVisible();
  return data;
}

const selectors = (page: Page) => page.getByRole('group', { name: '本次沟通 可多选' });

async function revealChoice(page: Page, label: string) {
  const button = selectors(page).getByRole('button', { name: label, exact: true });
  if (!(await button.isVisible())) await page.getByRole('button', { name: /^更多选项/ }).click();
  await expect(button).toBeVisible();
  return button;
}

async function expectNoHorizontalOverflow(page: Page, surface: Locator) {
  const size = await surface.evaluate(element => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    surface: element.clientWidth,
    surfaceScroll: element.scrollWidth,
  }));
  expect(size.document, '文档不应产生横向滚动').toBeLessThanOrEqual(size.viewport + 1);
  expect(size.body, 'body 不应产生横向滚动').toBeLessThanOrEqual(size.viewport + 1);
  expect(size.surfaceScroll, '工作台不能使用 overflow 隐藏挤出的操作').toBeLessThanOrEqual(size.surface + 1);
}

async function expectReachable(control: Locator) {
  await control.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
  await expect(control).toBeInViewport({ ratio: 1 });
  // The previous-record control is intentionally disabled at the first task;
  // its geometry remains asserted, but disabled Button suppresses pointer events.
  if (await control.isDisabled()) return;
  const hit = await control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return Boolean(target && (target === element || element.contains(target)));
  });
  expect(hit, '操作中心点不能被其他控件遮挡').toBe(true);
}

async function expectFullButtonText(button: Locator) {
  const clip = await button.evaluate(element => {
    const box = element.getBoundingClientRect();
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const clipped: string[] = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.left < box.left - 1 || rect.right > box.right + 1 || rect.top < box.top - 1 || rect.bottom > box.bottom + 1) clipped.push(node.textContent.trim());
      }
    }
    return clipped;
  });
  expect(clip, '按钮的全部文字必须在自身边界内').toEqual([]);
}

async function expectSelectTextFits(select: Locator) {
  const info = await select.evaluate(element => {
    const select = element as HTMLSelectElement;
    const style = getComputedStyle(select);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d')!;
    ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const text = select.selectedOptions[0]?.textContent || '';
    return {
      text,
      measured: ctx.measureText(text).width,
      available: select.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      availableHeight: select.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
      lineHeight: parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2,
      client: select.clientWidth,
    };
  });
  expect(info.text).toBe('已明确意向产品');
  expect(info.measured, `资料状态文字需要完整显示，可用宽度 ${info.available}`).toBeLessThanOrEqual(info.available + 1);
  expect(info.lineHeight, `资料状态行高不能被上下内边距裁切，可用高度 ${info.availableHeight}`).toBeLessThanOrEqual(info.availableHeight + 1);
}

for (const viewport of viewports) {
  test(`销售控件完整显示并可操作 ${viewport.width}x${viewport.height}`, async ({ page }) => {
    const { writes } = await openLayout(page, viewport.width, viewport.height);
    const surface = page.locator('.sc-workbench');
    await expect(surface.getByLabel('其他通话结果', { exact: true })).toHaveCount(0);
    for (const outcome of outcomes) {
      const button = await revealChoice(page, outcome.label);
      await expectFullButtonText(button);
      await expectReachable(button);
      await button.click();
      await expect(button).toHaveAttribute('aria-pressed', 'true');
      await expect(surface.getByRole('group', { name: '本次沟通 可多选' }).getByRole('button', { pressed: true })).toHaveCount(1);
      const followUp = surface.getByLabel(/^下次跟进/);
      if (outcome.followUp) await expect(followUp).toBeVisible();
      else await expect(followUp).toHaveCount(0);
      await button.click();
    }

    const header = surface.locator('.sw-customer-heading');
    const edit = header.getByRole('button', { name: '完善资料', exact: true });
    for (const name of ['上一位客户', '下一位客户', '更多客户操作']) {
      const control = header.getByRole('button', { name, exact: true });
      await expectReachable(control);
      if (viewport.width >= 768) {
        await expectFullButtonText(edit);
        const editBox = await edit.boundingBox();
        const box = await control.boundingBox();
        expect(editBox?.width || 0, '完善资料按钮不能继承图标按钮宽度').toBeGreaterThanOrEqual(88);
        const overlaps = Math.min(editBox!.x + editBox!.width, box!.x + box!.width) > Math.max(editBox!.x, box!.x) + 1
          && Math.min(editBox!.y + editBox!.height, box!.y + box!.height) > Math.max(editBox!.y, box!.y) + 1;
        expect(overlaps, '完善资料不能与分页操作重叠').toBe(false);
      }
    }

    if (viewport.width < 768) {
      await header.getByRole('button', { name: '更多客户操作' }).click();
      await expect(page.getByRole('menuitem', { name: '完善资料' })).toBeVisible();
      await page.keyboard.press('Escape');
      await surface.getByRole('button', { name: '打开客户队列', exact: true }).click();
      const queue = page.getByRole('dialog', { name: '客户队列', exact: true });
      const select = queue.getByRole('combobox', { name: '筛选资料状态', exact: true });
      await select.selectOption('has_interest');
      await expectSelectTextFits(select);
      await queue.getByRole('button', { name: '关闭', exact: true }).click();
    } else {
      const select = surface.getByRole('combobox', { name: '筛选资料状态', exact: true });
      if (await select.isVisible()) {
        await select.selectOption('has_interest');
        await expectSelectTextFits(select);
        const dimensions = await select.evaluate(element => {
          const label = element.closest('.sw-quality-filter')!;
          const style = getComputedStyle(label);
          return {
            select: element.getBoundingClientRect().width,
            content: label.getBoundingClientRect().width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
          };
        });
        expect(dimensions.select, '资料状态选择框应使用完整队列内容宽度').toBeGreaterThanOrEqual(dimensions.content - 2);
      } else {
        // The pre-existing narrow-desktop layout replaces the sidebar queue
        // with a customer picker; do not assert a hidden sidebar control.
        const customerPicker = surface.getByRole('combobox', { name: '选择客户', exact: true });
        await expectReachable(customerPicker);
        await expect(customerPicker.locator('option:not([disabled])')).toHaveCount(2);
      }
    }
    await expectNoHorizontalOverflow(page, surface);
    expect(writes).toEqual([]);
  });
}

for (const outcome of outcomes) {
  test(`手机展开 ${outcome.label} 后保存对应结果与跟进时间`, async ({ page }) => {
    const { writes } = await fixture(page);
    await open(page, 390);
    await (await revealChoice(page, outcome.label)).click();
    const memo = `合成验收：${outcome.label}`;
    await notes(page).fill(memo);
    if (outcome.followUp) await page.getByLabel(/^下次跟进/).fill('2026-10-20T10:30');
    await save(page).click();
    await expect(page.getByRole('heading', { name: '甲商家2' })).toBeVisible();
    expect(writes).toHaveLength(1);
    expect(writes[0].body).toMatchObject({
      outcome: outcome.value, outcomes: [outcome.value], quick_notes: [], notes: memo,
      next_follow_up_at: outcome.followUp ? '2026-10-20T02:30:00.000Z' : null,
    });
    expect(writes[0].body).not.toHaveProperty('enrichment');
  });
}

test('手机更多选项中选择已有服务商，刷新后无需再展开即可找到草稿', async ({ page }) => {
  const { writes } = await fixture(page);
  await open(page, 390);
  const label = '已有服务商（90天后轮换）';
  const selected = selectors(page).getByRole('button', { name: label, exact: true });
  await expect(selected).toHaveCount(0);
  await (await revealChoice(page, label)).click();
  await notes(page).fill('合成草稿：已有供应商，约定下次再联系');
  await page.reload();
  await expect(selected).toHaveAttribute('aria-pressed', 'true');
  await expect(notes(page)).toHaveValue('合成草稿：已有供应商，约定下次再联系');
  expect(writes).toEqual([]);
});
