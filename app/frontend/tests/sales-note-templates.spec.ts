import { expect, test, type Locator, type Page } from '@playwright/test';

const fixtureOrigin = process.env.T24_SALES_NOTE_TEMPLATES_BASE_URL || 'http://127.0.0.1:8906';
const templates = [
  { label: '本次未接通', text: '本次未接通。' },
  { label: '前台／老板不在', text: '前台接听，老板不在。' },
  { label: '英文沟通', text: '对方讲英文，暂未能有效沟通。' },
  { label: '老板有兴趣／忙', text: '老板有兴趣，目前比较忙。' },
  { label: '先看资料', text: '希望先看资料，关注：____。' },
  { label: '已有服务商', text: '已有服务商，补充：____。' },
  { label: '暂时不需要', text: '暂时不需要，原因：____。' },
  { label: '要求不再联系', text: '对方明确要求不再联系。' },
];

async function openFixture(page: Page, options: { width?: number; mode?: string } = {}) {
  const unexpected: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin !== fixtureOrigin || url.pathname.startsWith('/api/')) unexpected.push(request.url());
  });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === fixtureOrigin && !url.pathname.startsWith('/api/') ? route.continue() : route.abort('blockedbyclient');
  });
  const width = options.width || 1093;
  await page.setViewportSize({ width, height: 844 });
  await page.goto(`${fixtureOrigin}/${options.mode ? `?mode=${options.mode}` : ''}`);
  const surface = options.mode === 'record' ? page.getByTestId('isolated-call-record')
    : page.getByTestId(width < 768 ? 'sales-workbench-mobile' : 'sales-workbench-desktop');
  await expect(surface.getByLabel('沟通记录', { exact: true })).toBeVisible();
  const group = surface.getByRole('group', { name: '快捷备注模板', exact: true });
  await expect(group.getByRole('button')).toHaveCount(8);
  return { surface, group, notes: surface.getByLabel('沟通记录', { exact: true }), unexpected };
}

async function expectNoAutomaticBusinessChanges(page: Page, surface: Locator, unexpected: string[]) {
  await expect(page.getByLabel('请求保存次数')).toContainText('沟通结果保存 0');
  await expect(page.getByLabel('请求保存次数')).toContainText('独立资料保存 0');
  await expect(page.getByLabel('请求保存次数')).toContainText('一并提交资料 0');
  await expect(page.getByLabel('请求保存次数')).toContainText('演示拨号 尚未拨号');
  const isolated = surface.getByTestId('isolated-save-count');
  if (await isolated.count()) await expect(isolated).toHaveText('0');
  expect(unexpected, '模板和草稿不能发起真实业务 API 或外部请求').toEqual([]);
}

for (const [index, template] of templates.entries()) {
  test(`“${template.label}”追加完整模板并保留手工内容、结果和跟进时间`, async ({ page }) => {
    const { surface, group, notes, unexpected } = await openFixture(page);
    await surface.getByRole('button', { name: '待回访', exact: true }).click();
    await surface.getByLabel(/^下次跟进/).fill('2026-10-20T10:30');
    // Include meaningful trailing whitespace and alternate an existing newline.
    const previous = `已手工记录：店主姓陈，下午联系。  ${index % 2 ? '\n' : ''}`;
    await notes.fill(previous);
    await group.getByRole('button', { name: `插入模板：${template.text}`, exact: true }).click();
    const expected = `${previous}${previous.endsWith('\n') ? '' : '\n'}${template.text}`;
    await expect(notes).toHaveValue(expected);
    await expect(notes).toBeFocused();
    await expect.poll(() => notes.evaluate(element => {
      const textarea = element as HTMLTextAreaElement;
      return [textarea.selectionStart, textarea.selectionEnd];
    })).toEqual([expected.length, expected.length]);
    await expect(surface.getByRole('button', { name: '待回访', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(surface.getByLabel(/^下次跟进/)).toHaveValue('2026-10-20T10:30');
    await notes.fill(`${expected.replace('____', 'Google 广告')}\n销售补充：下周二继续确认。`);
    await expect(notes).toHaveValue(`${expected.replace('____', 'Google 广告')}\n销售补充：下周二继续确认。`);
    await expectNoAutomaticBusinessChanges(page, surface, unexpected);
  });
}

test('空白记录可连续组合模板，拒绝联系等文字不会自动改变通话结果', async ({ page }) => {
  const { surface, group, notes, unexpected } = await openFixture(page, { width: 390 });
  for (const template of templates) await group.getByRole('button', { name: `插入模板：${template.text}`, exact: true }).click();
  await expect(notes).toHaveValue(templates.map(template => template.text).join('\n'));
  await expect(surface.locator('.sc-outcomes button[aria-pressed="true"]')).toHaveCount(0);
  await expect(surface.getByLabel(/^下次跟进/)).toHaveCount(0);
  await expectNoAutomaticBusinessChanges(page, surface, unexpected);
});

test('10000字上限允许恰好填满，再插入保留原文并明确提示', async ({ page }) => {
  const { surface, group, notes, unexpected } = await openFixture(page);
  const text = templates[0].text;
  const previous = '中'.repeat(10000 - text.length - 1);
  await notes.fill(previous);
  await group.getByRole('button', { name: `插入模板：${text}`, exact: true }).click();
  const limit = `${previous}\n${text}`;
  expect(limit.length).toBe(10000);
  await expect(notes).toHaveValue(limit);
  await group.getByRole('button', { name: `插入模板：${templates[1].text}`, exact: true }).click();
  await expect(page.getByText('插入后会超出字数上限，请先删减沟通记录', { exact: true })).toBeVisible();
  await expect(notes).toHaveValue(limit);
  await expect(surface.locator('.sc-outcomes button[aria-pressed="true"]')).toHaveCount(0);
  await expectNoAutomaticBusinessChanges(page, surface, unexpected);
});

test('保存中与受保护记录禁用全部模板，恢复后保留原手工记录', async ({ page }) => {
  const { surface, group, notes, unexpected } = await openFixture(page, { mode: 'record' });
  await notes.fill('保护前的手工记录，不可覆盖。');
  for (const name of ['模拟保存中', '模拟禁止联系']) {
    await surface.getByRole('button', { name, exact: true }).click();
    await expect(notes).toBeDisabled();
    for (const template of templates) await expect(group.getByRole('button', { name: `插入模板：${template.text}`, exact: true })).toBeDisabled();
    await expect(notes).toHaveValue('保护前的手工记录，不可覆盖。');
    await surface.getByRole('button', { name, exact: true }).click();
    await expect(notes).toBeEnabled();
    for (const template of templates) await expect(group.getByRole('button', { name: `插入模板：${template.text}`, exact: true })).toBeEnabled();
  }
  await expect(notes).toHaveValue('保护前的手工记录，不可覆盖。');
  await expectNoAutomaticBusinessChanges(page, surface, unexpected);
});

test('模板与手工补充一起恢复草稿，结果及跟进时间保持原值', async ({ page }) => {
  const { surface, group, notes, unexpected } = await openFixture(page, { width: 390 });
  await surface.getByRole('button', { name: '有意向', exact: true }).click();
  await surface.getByLabel(/^下次跟进/).fill('2026-10-20T10:30');
  await notes.fill('原记录：对方咨询官网。');
  await group.getByRole('button', { name: `插入模板：${templates[3].text}`, exact: true }).click();
  await notes.press('End');
  await notes.press('Enter');
  await notes.pressSequentially('手工补充：周二下午老板在店。');
  const expected = await notes.inputValue();
  await page.reload();
  await expect(notes).toHaveValue(expected);
  await expect(surface.getByRole('button', { name: '有意向', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(surface.getByLabel(/^下次跟进/)).toHaveValue('2026-10-20T10:30');
  await expectNoAutomaticBusinessChanges(page, surface, unexpected);
});

for (const width of [1093, 390, 320]) {
  test(`快捷模板在${width}px均完整显示、可点击且不横向挤出`, async ({ page }) => {
    const { surface, group, notes, unexpected } = await openFixture(page, { width });
    for (const template of templates) {
      const button = group.getByRole('button', { name: `插入模板：${template.text}`, exact: true });
      await button.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
      await expect(button).toBeInViewport({ ratio: 1 });
      const metrics = await button.evaluate(element => {
        const box = element.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(element);
        const text = range.getBoundingClientRect();
        const target = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return { height: box.height, fits: text.left >= box.left - 1 && text.right <= box.right + 1 && text.top >= box.top - 1 && text.bottom <= box.bottom + 1, hit: Boolean(target && (element === target || element.contains(target))) };
      });
      expect(metrics.fits, '简短模板标签必须完整显示').toBe(true);
      expect(metrics.hit, '模板中心点不能被固定控件遮挡').toBe(true);
      expect(metrics.height).toBeGreaterThanOrEqual(width < 768 ? 44 : 32);
      await button.click();
      await expect(notes).toBeFocused();
    }
    const sizes = await surface.evaluate(element => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth, surface: element.clientWidth, scroll: element.scrollWidth }));
    expect(sizes.document).toBeLessThanOrEqual(sizes.viewport + 1);
    expect(sizes.body).toBeLessThanOrEqual(sizes.viewport + 1);
    expect(sizes.scroll).toBeLessThanOrEqual(sizes.surface + 1);
    await expectNoAutomaticBusinessChanges(page, surface, unexpected);
  });
}
