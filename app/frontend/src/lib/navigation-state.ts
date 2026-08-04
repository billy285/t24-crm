export const getSafeInternalPath = (value?: string | null, fallback = '') => {
  const raw = String(value || '').trim();
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return fallback;
  try {
    const parsed = new URL(raw, 'https://t24-crm.local');
    if (parsed.origin !== 'https://t24-crm.local') return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
};

export const buildReturnLink = (path: string, returnTo: string, from?: string) => {
  const target = new URL(path, 'https://t24-crm.local');
  const safeReturnTo = getSafeInternalPath(returnTo);
  if (safeReturnTo) target.searchParams.set('returnTo', safeReturnTo);
  if (from) target.searchParams.set('from', from);
  return `${target.pathname}${target.search}${target.hash}`;
};

export const getReturnLabel = (path?: string | null) => {
  const safePath = getSafeInternalPath(path);
  if (safePath.startsWith('/management-decisions')) {
    const target = new URL(safePath, 'https://t24-crm.local');
    return target.searchParams.get('section') === 'quality' ? '返回数据质量中心' : '返回经营分类与项目';
  }
  if (safePath.startsWith('/tasks')) return '返回任务协作';
  if (safePath.startsWith('/finance')) return '返回财务管理';
  if (safePath.startsWith('/service-board')) return '返回服务进度看板';
  return '返回上一页';
};
