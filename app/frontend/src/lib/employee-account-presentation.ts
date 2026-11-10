export function employeePasswordState(employee: { has_login_password?: boolean }) {
  if (employee.has_login_password === true) return { label: '密码已设置', className: 'text-emerald-700' };
  if (employee.has_login_password === false) return { label: '密码未设置', className: 'text-amber-700' };
  return { label: '密码状态待确认', className: 'text-slate-500' };
}
