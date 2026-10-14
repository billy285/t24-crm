import { expect, test, type Locator, type Page } from '@playwright/test';

// Runs only against the isolated fixture origin. The fixture blocks real API,
// dialer, navigation, credentials and beforeunload handlers before imports.
const fixtureOrigin = process.env.T24_SALES_CONTROLS_BASE_URL || 'http://127.0.0.1:8905';
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

async function openFixture(page: Page, width: number, height: number) {
  const escapedOrigin = fixtureOrigin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const allowed = new RegExp(`^${escapedOrigin}(?:/|$)`);
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!allowed.test(url.href) || url.pathname.startsWith('/api/')) return route.abort('blockedbyclient');
    return route.continue();
  });
  await page.setViewportSize({ width, height });
  await page.goto(fixtureOrigin);
  const surface = page.getByTestId(width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeVisible();
  await expect(surface.locator('h2')).toContainText('InternationalRestaurantAndHospitalityManagementCompany');
  return surface;
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
      client: select.clientWidth,
    };
  });
  expect(info.text).toBe('已明确意向产品');
  expect(info.measured, `资料状态文字需要完整显示，可用宽度 ${info.available}`).toBeLessThanOrEqual(info.available + 1);
}

for (const viewport of viewports) {
  test(`销售控件完整显示并可操作 ${viewport.width}x${viewport.height}`, async ({ page }) => {
    const surface = await openFixture(page, viewport.width, viewport.height);
    await expect(surface.locator('.sc-outcomes button')).toHaveCount(8);
    await expect(surface.getByLabel('其他通话结果', { exact: true })).toHaveCount(0);
    for (const outcome of outcomes) {
      const button = surface.getByRole('button', { name: outcome.label, exact: true });
      await expectFullButtonText(button);
      await expectReachable(button);
      await button.click();
      await expect(button).toHaveAttribute('aria-pressed', 'true');
      expect(await surface.locator('.sc-outcomes button[aria-pressed="true"]').count()).toBe(1);
      const followUp = surface.getByLabel(/^下次跟进/);
      if (outcome.followUp) await expect(followUp).toBeVisible();
      else await expect(followUp).toHaveCount(0);
    }

    const header = surface.locator('.sw-customer-heading');
    const edit = header.getByRole('button', { name: '完善资料', exact: true });
    await expectReachable(edit);
    await expectFullButtonText(edit);
    const editBox = await edit.boundingBox();
    expect(editBox?.width || 0, '完善资料按钮不能继承图标按钮宽度').toBeGreaterThanOrEqual(88);
    for (const name of ['上一位客户', '下一位客户', '更多客户操作']) {
      const control = header.getByRole('button', { name, exact: true });
      await expectReachable(control);
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      const overlaps = Math.min(editBox!.x + editBox!.width, box!.x + box!.width) > Math.max(editBox!.x, box!.x) + 1
        && Math.min(editBox!.y + editBox!.height, box!.y + box!.height) > Math.max(editBox!.y, box!.y) + 1;
      expect(overlaps, '完善资料不能与前后客户或更多按钮相互覆盖').toBe(false);
    }

    if (viewport.width < 768) {
      await surface.getByRole('button', { name: '打开客户队列', exact: true }).click();
      const queue = page.getByRole('dialog', { name: '客户队列', exact: true });
      const select = queue.getByRole('combobox', { name: '筛选资料状态', exact: true });
      await select.selectOption('has_interest');
      await expectSelectTextFits(select);
      await queue.getByRole('button', { name: 'Close', exact: true }).click();
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
    await expect(page.getByLabel('请求保存次数')).toContainText('沟通结果保存 0');
    await expect(page.getByLabel('请求保存次数')).toContainText('演示拨号 尚未拨号');
  });
}

for (const outcome of outcomes) {
  test(`展开后的 ${outcome.label} 保留原提交结果与跟进语义`, async ({ page }) => {
    const surface = await openFixture(page, 1093, 824);
    const button = surface.getByRole('button', { name: outcome.label, exact: true });
    await button.click();
    await surface.getByLabel('沟通记录', { exact: true }).fill(`合成验收：${outcome.label}；不产生真实联系记录`);
    if (outcome.followUp) await surface.getByLabel(/^下次跟进/).fill('2026-10-20T10:30');
    await surface.getByRole('button', { name: '保存并下一位', exact: true }).click();
    await expect(page.getByLabel('请求保存次数')).toContainText('沟通结果保存 1');
    await expect(surface.locator('h2')).toHaveText('下一位合成商家');
    const log = page.locator('.qa-log article').filter({ hasText: '/result' }).first();
    const payload = JSON.parse(await log.locator('pre').textContent() || '{}');
    expect(payload).toMatchObject({
      outcome: outcome.value,
      notes: `合成验收：${outcome.label}；不产生真实联系记录`,
      next_follow_up_at: outcome.followUp ? '2026-10-20T02:30:00.000Z' : null,
    });
    expect(payload).not.toHaveProperty('enrichment');
    await expect(page.getByLabel('请求保存次数')).toContainText('独立资料保存 0');
    await expect(page.getByLabel('请求保存次数')).toContainText('一并提交资料 0');
  });
}

test('展开结果选择继续保留未保存草稿且不发生真实网络请求', async ({ page }) => {
  const unexpected: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin !== fixtureOrigin || url.pathname.startsWith('/api/')) unexpected.push(request.url());
  });
  const surface = await openFixture(page, 390, 844);
  await surface.getByRole('button', { name: '已有服务商（90天后轮换）', exact: true }).click();
  await surface.getByLabel('沟通记录', { exact: true }).fill('合成草稿：已有供应商，约定下次再联系');
  await page.reload();
  await expect(surface.getByRole('button', { name: '已有服务商（90天后轮换）', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toHaveValue('合成草稿：已有供应商，约定下次再联系');
  await expect(page.getByLabel('请求保存次数')).toContainText('沟通结果保存 0');
  expect(unexpected).toEqual([]);
});
