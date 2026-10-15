import { expect, test, type Locator, type Page } from '@playwright/test';

const baseUrl = process.env.T24_CUSTOMERS_DIALOG_BASE_URL || 'http://127.0.0.1:8917';
const owner = { id: 101, name: '客户弹窗验收老板', role: 'super_admin', status: 'active' };

async function openCustomerForm(page: Page) {
  const writes: string[] = [];
  await page.addInitScript(employee => {
    localStorage.setItem('emp_auth_token', 'customer-dialog-fixture-token');
    localStorage.setItem('token', 'customer-dialog-fixture-token');
    localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, owner);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      writes.push(`${request.method()} ${path}`);
      return route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: '关闭表单验收不允许写入' }) });
    }
    const data = path.endsWith('/emp-auth/me') ? owner
      : path.includes('/app-config') ? { items: {} }
      : path.includes('/admin/settings') ? { backend_vars: {}, frontend_vars: {} }
      : path.includes('/entities/employees') ? { items: [owner], total: 1 }
      : { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${baseUrl}/customers`);
  await page.getByRole('button', { name: '新增客户', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '新增客户', exact: true });
  await expect(dialog).toBeVisible();
  return { dialog, writes };
}

async function expectCloseCenterReceivesPointer(close: Locator) {
  await expect(close).toBeVisible();
  await expect.poll(() => close.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return {
      receivesHit: hit === element || Boolean(hit && element.contains(hit)),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  })).toEqual({ receivesHit: true, width: 44, height: 44 });
}

for (const viewport of [{ width: 1093, height: 824 }, { width: 390, height: 844 }]) {
  test.describe(`客户表单关闭 ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test('未修改时关闭按钮和取消直接关闭，按钮中心真实接收点击', async ({ page }) => {
      const prompts: string[] = [];
      page.on('dialog', async prompt => { prompts.push(prompt.type()); await prompt.dismiss(); });
      const { dialog, writes } = await openCustomerForm(page);
      const close = dialog.getByRole('button', { name: 'Close', exact: true });
      await expectCloseCenterReceivesPointer(close);
      if (process.env.T24_CUSTOMERS_DIALOG_SCREENSHOT_DIR) {
        await page.screenshot({ path: `${process.env.T24_CUSTOMERS_DIALOG_SCREENSHOT_DIR}/customer-close-${viewport.width}.png`, animations: 'disabled' });
      }
      await close.click();
      await expect(dialog).toHaveCount(0);
      await page.getByRole('button', { name: '新增客户', exact: true }).click();
      await expect(dialog).toBeVisible();
      await dialog.getByTestId('customer-form-actions').getByRole('button', { name: '取消', exact: true }).click();
      await expect(dialog).toHaveCount(0);
      expect(prompts).toEqual([]);
      expect(writes).toEqual([]);
    });

    for (const action of ['关闭按钮', '取消按钮']) {
      test(`修改后${action}取消确认保留草稿，确认放弃后关闭且不写入`, async ({ page }) => {
        const { dialog, writes } = await openCustomerForm(page);
        const phone = dialog.getByLabel('电话 *', { exact: true });
        await phone.fill('+1 (310) 555-0123');
        const dismiss = action === '关闭按钮'
          ? dialog.getByRole('button', { name: 'Close', exact: true })
          : dialog.getByTestId('customer-form-actions').getByRole('button', { name: '取消', exact: true });
        if (action === '关闭按钮') await expectCloseCenterReceivesPointer(dismiss);
        let promptCount = 0;
        page.once('dialog', async prompt => {
          expect(prompt.type()).toBe('confirm');
          expect(prompt.message()).toContain('尚未保存');
          promptCount += 1;
          await prompt.dismiss();
        });
        await dismiss.click();
        await expect.poll(() => promptCount).toBe(1);
        await expect(dialog).toBeVisible();
        await expect(phone).toHaveValue('+1 (310) 555-0123');
        expect(writes).toEqual([]);
        page.once('dialog', async prompt => {
          expect(prompt.type()).toBe('confirm');
          expect(prompt.message()).toContain('尚未保存');
          promptCount += 1;
          await prompt.accept();
        });
        await dismiss.click();
        await expect(dialog).toHaveCount(0);
        expect(promptCount).toBe(2);
        expect(writes).toEqual([]);
      });
    }
  });
}
