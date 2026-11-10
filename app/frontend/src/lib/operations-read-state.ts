const sourceLabels = ['任务', '回访', '服务问题', '客户资料'] as const;

export function operationsReadState(results: PromiseSettledResult<unknown>[]) {
  const missing = sourceLabels.filter((_, index) => results[index]?.status !== 'fulfilled');
  return {
    missing,
    actionsIncomplete: sourceLabels.slice(0, 3).some((_, index) => results[index]?.status !== 'fulfilled'),
    message: missing.length ? `${missing.join('、')}暂未完整读取；已载入事项仍可继续查看，请重新读取后核对总数。` : '',
  };
}

export function operationsMetric(value: number, incomplete: boolean) {
  return incomplete ? (value > 0 ? `${value} · 待核对` : '待重试') : value;
}
