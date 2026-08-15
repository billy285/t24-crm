import { expect, test, type Page, type Route } from '@playwright/test';

const baseUrl = process.env.T24_WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const employee = { id: 1, name: '测试管理员', role: 'admin', status: 'active' };
const now = new Date();
const currentMonth = now.toISOString().slice(0, 7);

type PaymentStatus = 'pending' | 'partial' | 'paid' | 'failed' | 'returned' | 'supplemental';

const payrollItem = (id: number, paymentStatus: PaymentStatus) => ({
  id,
  employee_id: id,
  employee_name: `测试员工 ${id}`,
  employee_code: `T24-${String(id).padStart(3, '0')}`,
  department: '运营部',
  hire_date: '2026-01-01',
  payment_method: 'bank_card',
  payment_account_masked: `•••• ${String(8800 + id)}`,
  base_salary: 5_000,
  fixed_performance: 500,
  commission: 0,
  bonus: 0,
  allowance: 0,
  reimbursement: 0,
  absence_deduction: 0,
  performance_deduction: 0,
  salary_advance_deduction: 0,
  other_deduction: 0,
  payment_status: paymentStatus,
  payment_date: paymentStatus === 'paid' ? `${currentMonth}-01` : null,
  payment_reference: paymentStatus === 'paid' ? `BANK-${id}` : null,
  receipt_url: null,
  notes: null,
  gross_amount: 5_500,
  deduction_amount: 0,
  net_amount: 5_500,
});

const initialItems = [
  payrollItem(1, 'pending'),
  payrollItem(2, 'pending'),
  payrollItem(3, 'pending'),
  payrollItem(4, 'paid'),
];

const payrollResponse = (status: 'confirmed' | 'paid') => ({
  sheet: { id: 10, month: currentMonth, status, currency: 'CNY', reopen_reason: null },
  items: status === 'paid'
    ? initialItems.map(item => ({
        ...item,
        payment_status: 'paid',
        payment_date: item.payment_date || `${currentMonth}-15`,
      }))
    : initialItems,
  totals: { gross: 22_000, deductions: 0, net: 22_000 },
});

type PayrollMockOptions = {
  onTransition: (route: Route) => Promise<void>;
  getSheetStatus?: () => 'confirmed' | 'paid';
};

async function mockPayrollApi(page: Page, options: PayrollMockOptions) {
  await page.addInitScript(({ emp }) => {
    window.localStorage.setItem('emp_auth_token', 'payroll-bulk-paid-token');
    window.localStorage.setItem('token', 'payroll-bulk-paid-token');
    window.localStorage.setItem('emp_auth_data', JSON.stringify(emp));
  }, { emp: employee });

  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path.endsWith('/emp-auth/me')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(employee) });
      return;
    }
    if (path.endsWith(`/payroll/${currentMonth}/transition`)) {
      await options.onTransition(route);
      return;
    }
    if (path.endsWith('/payroll/employees')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      return;
    }
    if (path.endsWith('/payroll') && request.method() === 'GET') {
      const status = options.getSheetStatus?.() || 'confirmed';
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payrollResponse(status)) });
      return;
    }
    if (path.includes('/app-config')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: {} }) });
      return;
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}

const openBulkPaidDialog = async (page: Page) => {
  await page.goto(`${baseUrl}/payroll`);
  await expect(page.getByRole('heading', { name: '工资表与人力成本' })).toBeVisible();
  await page.getByRole('button', { name: /登记 \d+ 人并锁定|完成并锁定整表/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog).toBeFocused();
  return dialog;
};

test('整表发放先确认日期、批量登记待发明细且提交中只发送一次', async ({ page }) => {
  let transitionCount = 0;
  let transitionPayload: Record<string, unknown> | null = null;
  let sheetStatus: 'confirmed' | 'paid' = 'confirmed';
  let releaseTransition: () => void = () => undefined;
  const transitionGate = new Promise<void>(resolve => { releaseTransition = resolve; });

  await mockPayrollApi(page, {
    getSheetStatus: () => sheetStatus,
    onTransition: async route => {
      transitionCount += 1;
      transitionPayload = route.request().postDataJSON();
      await transitionGate;
      sheetStatus = 'paid';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ month: currentMonth, status: 'paid', message: '工资表状态已更新' }),
      });
    },
  });

  const dialog = await openBulkPaidDialog(page);
  const paymentDate = `${currentMonth}-15`;
  await dialog.locator('input[type="date"]').fill(paymentDate);
  const confirmButton = dialog.getByRole('button', { name: /确认.*发放|发放.*锁定/ });

  await confirmButton.click();
  await expect.poll(() => transitionCount).toBe(1);
  await expect(confirmButton).toBeDisabled();
  await confirmButton.evaluate(button => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await page.waitForTimeout(50);
  expect(transitionCount).toBe(1);
  expect(transitionPayload).toMatchObject({
    action: 'mark_paid',
    confirm_all_pending: true,
    payment_date: paymentDate,
  });

  releaseTransition();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('已发放锁定', { exact: true })).toBeVisible();
  expect(transitionCount).toBe(1);
});

test('整表发放 409 直接显示后端中文原因', async ({ page }) => {
  const backendDetail = '工资表状态已由其他人更新，请刷新后重试';
  let transitionCount = 0;
  let sheetStatus: 'confirmed' | 'paid' = 'confirmed';

  await mockPayrollApi(page, {
    getSheetStatus: () => sheetStatus,
    onTransition: async route => {
      transitionCount += 1;
      sheetStatus = 'paid';
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: backendDetail }),
      });
    },
  });

  const dialog = await openBulkPaidDialog(page);
  await dialog.locator('input[type="date"]').fill(`${currentMonth}-16`);
  await dialog.getByRole('button', { name: /确认.*发放|发放.*锁定/ }).click();

  await expect(page.getByText(backendDetail, { exact: true })).toBeVisible();
  await expect(dialog).toBeHidden();
  await expect(page.getByText('已发放锁定', { exact: true })).toBeVisible();
  expect(transitionCount).toBe(1);
});
