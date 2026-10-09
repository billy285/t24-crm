import { expect, test } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5196';
const employee = { id: 1, name: '任务布局测试管理员', role: 'admin', status: 'active' };
const longNote = '先联系客户确认资料。\n' + '保留客户提供的原始要求和每一项交付约定。'.repeat(55) + '\n最后一项：下周再次确认。';
const systemNote = '发现问题：客户资料尚未齐全。\n建议处理：先确认联系人，再补充资料。\n问题编号：QA-MOBILE-001\n' + '补充说明不应挤压主要操作。'.repeat(45);

for (const width of [320, 390, 430]) {
  test(`手机任务说明收起后主操作可达，展开保留完整资料 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(emp => {
      localStorage.setItem('emp_auth_token', 'task-layout-fixture');
      localStorage.setItem('token', 'task-layout-fixture');
      localStorage.setItem('emp_auth_data', JSON.stringify(emp));
    }, employee);
    const writes: string[] = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET') writes.push(`${route.request().method()} ${path}`);
      let data: unknown = { items: [] };
      if (path.endsWith('/emp-auth/me')) data = employee;
      else if (path.includes('/entities/tasks')) data = { items: [
        { id: 801, title: '长说明任务', source_type: 'manual', assignee_name: employee.name, status: 'pending', priority: 'medium', notes: longNote, due_date: '2026-10-09' },
        { id: 802, title: '系统任务说明', source_type: 'system', assignee_name: employee.name, status: 'in_progress', priority: 'high', notes: systemNote, automation_issue_id: 9, due_date: '2026-10-09' },
        { id: 803, title: '简短任务', source_type: 'manual', assignee_name: employee.name, status: 'pending', priority: 'low', notes: '确认联系人' },
      ] };
      else if (path.includes('/entities/employees')) data = { items: [employee] };
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto(`${baseUrl}/tasks?view=team`);
    const plain = page.locator('#task-row-801');
    const system = page.locator('#task-row-802');
    await expect(plain.getByRole('heading', { name: '长说明任务' })).toBeVisible();
    for (const [card, fullNote, action] of [[plain, longNote, '开始处理'], [system, systemNote, '完成并记录']] as const) {
      const detail = card.getByRole('group', { name: '任务说明' });
      await expect(detail).not.toHaveAttribute('open');
      await expect(card.locator('.mobile-task-note-full')).toBeHidden();
      const box = await card.boundingBox();
      const actionBox = await card.getByRole('button', { name: action, exact: true }).boundingBox();
      expect(actionBox!.y - box!.y).toBeLessThan(460);
      expect(actionBox!.height).toBeGreaterThanOrEqual(44);
      await card.getByText('展开说明', { exact: true }).click();
      await expect(detail).toHaveAttribute('open');
      await expect(card.locator('.mobile-task-note-full')).toHaveText(fullNote);
      await card.getByText('收起说明', { exact: true }).click();
      await expect(detail).not.toHaveAttribute('open');
    }
    await expect(system.locator('summary')).toContainText('先确认联系人，再补充资料。');
    await expect(page.locator('#task-row-803').getByText('确认联系人', { exact: true })).toBeVisible();
    await expect(page.locator('#task-row-803 summary')).toHaveCount(0);
    const widthResult = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    expect(widthResult.document).toBeLessThanOrEqual(widthResult.viewport);
    expect(writes).toEqual([]);
    if (width === 390 && process.env.T24_MOBILE_POLISH_SCREENSHOT_DIR) {
      await plain.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${process.env.T24_MOBILE_POLISH_SCREENSHOT_DIR}/local-mock-task-summary-390.png` });
    }
  });
}
