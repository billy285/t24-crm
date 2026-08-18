import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const admin = { id: 1, name: '成交测试管理员', role: 'admin', status: 'active' };

async function fulfillJson(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
}

async function seedAuth(page: Page) {
  await page.addInitScript(({ employee }) => {
    window.localStorage.setItem('emp_auth_token', 'deal-finalize-test-token');
    window.localStorage.setItem('token', 'deal-finalize-test-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(employee));
  }, { employee: admin });
}

test('成交已保存但 finalize 未完成时逐项提示并可手动重试且不重复成交', async ({ page }) => {
  await seedAuth(page);
  let deals = [] as Array<Record<string, unknown>>;
  let dealCreateCount = 0;
  let finalizeCount = 0;
  const finalizeBodies: Array<Record<string, unknown>> = [];

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, admin);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path === '/api/v1/entities/customers' || path === '/api/v1/entities/customers/all') {
      return fulfillJson(route, {
        items: [
          {
            id: 31,
            customer_code: 'FINAL-031',
            business_name: 'Finalize 测试客户',
            contact_name: '测试负责人',
            phone: '555-0031',
            status: 'following',
            sales_person: admin.name,
          },
          ...Array.from({ length: 20 }, (_, index) => ({
            id: 100 + index,
            customer_code: `SCROLL-${String(index + 1).padStart(3, '0')}`,
            business_name: `下拉选择测试商家 ${String(index + 1).padStart(2, '0')}`,
            status: 'following',
            sales_person: admin.name,
          })),
        ],
        total: 21,
      });
    }
    if (path === '/api/v1/entities/deals' && request.method() === 'GET') {
      return fulfillJson(route, { items: deals, total: deals.length });
    }
    if (path === '/api/v1/entities/deals' && request.method() === 'POST') {
      dealCreateCount += 1;
      const payload = request.postDataJSON();
      const created = { id: 501, ...payload };
      deals = [created];
      return fulfillJson(route, created, 201);
    }
    if (path === '/api/v1/entities/deals/501/finalize' && request.method() === 'POST') {
      finalizeCount += 1;
      finalizeBodies.push(request.postDataJSON());
      if (finalizeCount === 1) {
        return fulfillJson(route, {
          deal_id: 501,
          complete: false,
          retryable: true,
          steps: {
            subscription: { status: 'skipped', message: '本次成交不需要建立订阅', retryable: false },
            customer: { status: 'completed', message: '客户状态已更新为已成交', resource_id: 31, retryable: false },
            service_board: { status: 'failed', message: '服务看板暂时不可用，请重试', retryable: true },
          },
        });
      }
      return fulfillJson(route, {
        deal_id: 501,
        complete: true,
        retryable: false,
        steps: {
          subscription: { status: 'skipped', message: '本次成交不需要建立订阅', retryable: false },
          customer: { status: 'completed', message: '客户已是成交状态', resource_id: 31, retryable: false },
          service_board: { status: 'completed', message: '已生成服务看板和 6 个前期任务', resource_id: 91, created_count: 6, retryable: false },
        },
      });
    }
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });

  await page.goto(`${baseUrl}/deals`);
  await page.getByRole('button', { name: '录入成交' }).click();
  const dialog = page.getByRole('dialog', { name: '录入成交' });
  const customerPicker = dialog.getByRole('combobox').first();
  const customerPickerBox = await customerPicker.boundingBox();
  await customerPicker.click();
  const customerSearchPanel = page.locator('[data-slot="combobox-content"]');
  const customerSearchPanelBox = await customerSearchPanel.boundingBox();
  expect(customerPickerBox).not.toBeNull();
  expect(customerSearchPanelBox).not.toBeNull();
  const customerPanelWidthDelta = Math.abs((customerSearchPanelBox?.width || 0) - (customerPickerBox?.width || 0));
  expect(customerPanelWidthDelta / (customerPickerBox?.width || 1)).toBeLessThan(0.03);
  const customerList = page.getByRole('listbox', { name: 'Suggestions' });
  const customerListBox = await customerList.boundingBox();
  expect(customerListBox).not.toBeNull();
  await expect(customerList.getByRole('option')).toHaveCount(21);
  await page.mouse.move(
    (customerListBox?.x || 0) + (customerListBox?.width || 0) / 2,
    (customerListBox?.y || 0) + (customerListBox?.height || 0) / 2,
  );
  await page.mouse.wheel(0, 720);
  await expect.poll(() => customerList.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await page.getByPlaceholder('搜索商家名称或编号').fill('FINAL-031');
  await expect(page.getByRole('listbox', { name: 'Suggestions' }).getByRole('option')).toHaveCount(1);
  await page.getByRole('option', { name: 'Finalize 测试客户' }).click();
  await expect(dialog.getByRole('combobox').first()).toContainText('Finalize 测试客户');
  await dialog.getByLabel('基础套餐').check();
  await dialog.getByPlaceholder('0.00').fill('198');
  await dialog.getByRole('switch').first().click();
  await dialog.getByRole('button', { name: '保存', exact: true }).click();

  const pending = page.getByTestId('deal-finalize-pending-501');
  await expect(pending).toBeVisible();
  await expect(pending).toContainText('成交 #501 已保存，交接未完成');
  await expect(pending).toContainText('服务看板：服务看板暂时不可用，请重试');
  await expect(page.getByText('保存失败', { exact: true })).toHaveCount(0);
  expect(dealCreateCount).toBe(1);
  expect(finalizeCount).toBe(1);

  await page.reload();
  const restoredPending = page.getByTestId('deal-finalize-pending-501');
  await expect(restoredPending).toBeVisible();
  await expect(restoredPending).toContainText('服务看板：服务看板暂时不可用，请重试');
  expect(dealCreateCount).toBe(1);
  expect(finalizeCount).toBe(1);

  await page.getByRole('button', { name: '继续完成交接 #501' }).click();
  await expect(restoredPending).toHaveCount(0);
  await expect(page.getByText('成交 #501 的交接已继续完成')).toBeVisible();
  expect(dealCreateCount).toBe(1);
  expect(finalizeCount).toBe(2);
  expect(finalizeBodies).toEqual([
    { ensure_subscription: false, auto_renew: false, create_service_board: true },
    { ensure_subscription: false, auto_renew: false, create_service_board: true },
  ]);
});

test('成交 POST 响应丢失时查询恢复已提交记录并继续 finalize 而不重复 POST', async ({ page }) => {
  await seedAuth(page);
  let deals = [] as Array<Record<string, unknown>>;
  let dealCreateCount = 0;
  let finalizeCount = 0;

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/emp-auth/me')) return fulfillJson(route, admin);
    if (path.includes('/app-config')) return fulfillJson(route, { items: [] });
    if (path === '/api/v1/entities/customers' || path === '/api/v1/entities/customers/all') {
      return fulfillJson(route, {
        items: [{
          id: 32,
          customer_code: 'FINAL-032',
          business_name: '响应丢失测试客户',
          contact_name: '测试负责人',
          phone: '555-0032',
          status: 'following',
          sales_person: admin.name,
        }],
        total: 1,
      });
    }
    if (path === '/api/v1/entities/deals' && request.method() === 'GET') {
      return fulfillJson(route, { items: deals, total: deals.length });
    }
    if (path === '/api/v1/entities/deals' && request.method() === 'POST') {
      dealCreateCount += 1;
      const payload = request.postDataJSON();
      deals = [{ id: 502, ...payload }];
      return route.abort('failed');
    }
    if (path === '/api/v1/entities/deals/502/finalize' && request.method() === 'POST') {
      finalizeCount += 1;
      return fulfillJson(route, {
        deal_id: 502,
        complete: true,
        retryable: false,
        steps: {
          subscription: { status: 'skipped', message: '本次成交不需要建立订阅', retryable: false },
          customer: { status: 'completed', message: '客户状态已更新为已成交', resource_id: 32, retryable: false },
          service_board: { status: 'skipped', message: '本次不生成服务看板', retryable: false },
        },
      });
    }
    if (path.includes('/entities/')) return fulfillJson(route, { items: [], total: 0 });
    return fulfillJson(route, {});
  });

  await page.goto(`${baseUrl}/deals`);
  await page.getByRole('button', { name: '录入成交' }).click();
  const dialog = page.getByRole('dialog', { name: '录入成交' });
  await dialog.getByRole('combobox').first().click();
  await page.getByPlaceholder('搜索商家名称或编号').fill('FINAL-032');
  await page.getByRole('option', { name: '响应丢失测试客户' }).click();
  await dialog.getByLabel('基础套餐').check();
  await dialog.getByPlaceholder('0.00').fill('198');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();

  await expect(page.getByText('成交 #502 已在服务器保存，正在继续完成交接')).toBeVisible();
  await expect(page.getByText('成交 #502 已保存并完成交接')).toBeVisible();
  await expect(page.getByText('保存失败', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('deal-finalize-pending-list')).toHaveCount(0);
  await expect.poll(() => dealCreateCount).toBe(1);
  await expect.poll(() => finalizeCount).toBe(1);
});
