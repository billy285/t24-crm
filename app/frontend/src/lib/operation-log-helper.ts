import { invokeWithAuth } from './tokenStore';

export const operationActionTypes = [
  'user_note',
  'create_customer', 'edit_customer', 'delete_customer',
  'view_password',
  'create_follow_up', 'edit_follow_up', 'delete_follow_up',
  'create_media_account', 'edit_media_account', 'delete_media_account',
  'create_material', 'edit_material', 'delete_material',
  'complete_service_task',
  'export_data',
  'create_deal', 'edit_deal',
  'create_payment', 'edit_payment', 'delete_payment',
  'create_subscription', 'edit_subscription', 'delete_subscription',
  'confirm_subscription_renewal', 'stop_subscription_renewal', 'change_subscription_package',
  'enable_subscription_auto_renew', 'switch_subscription_to_manual_collection',
  'create_customer_expense', 'edit_customer_expense', 'delete_customer_expense',
  'create_company_expense', 'edit_company_expense', 'delete_company_expense',
  'close_finance_month', 'reopen_finance_month',
  'other',
] as const;

export type ActionType = typeof operationActionTypes[number];

export const actionTypeLabels: Record<ActionType, string> = {
  user_note: '用户备注（非系统审计）',
  create_customer: '新增客户',
  edit_customer: '编辑客户',
  delete_customer: '删除客户',
  view_password: '查看密码',
  create_follow_up: '新增跟进',
  edit_follow_up: '编辑跟进',
  delete_follow_up: '删除跟进',
  create_media_account: '新增媒体账号',
  edit_media_account: '编辑媒体账号',
  delete_media_account: '删除媒体账号',
  create_material: '新增素材',
  edit_material: '编辑素材',
  delete_material: '删除素材',
  complete_service_task: '完成服务任务',
  export_data: '导出数据',
  create_deal: '新增成交',
  edit_deal: '编辑成交',
  create_payment: '新增收款',
  edit_payment: '编辑收款',
  delete_payment: '删除收款',
  create_subscription: '新增套餐续费',
  edit_subscription: '编辑套餐续费',
  delete_subscription: '删除套餐续费',
  confirm_subscription_renewal: '确认套餐续费',
  stop_subscription_renewal: '停止套餐续费',
  change_subscription_package: '变更套餐',
  enable_subscription_auto_renew: '开启自动续费',
  switch_subscription_to_manual_collection: '切换手动收款',
  create_customer_expense: '新增客户支出',
  edit_customer_expense: '编辑客户支出',
  delete_customer_expense: '删除客户支出',
  create_company_expense: '新增公司支出',
  edit_company_expense: '编辑公司支出',
  delete_company_expense: '删除公司支出',
  close_finance_month: '月度关账',
  reopen_finance_month: '重新打开账期',
  other: '其他操作',
};

export async function logOperation(params: {
  customerId?: number;
  actionType: ActionType;
  actionDetail: string;
  // Retained while older call sites are migrated; never transmitted. The
  // authenticated backend is the only source of operator attribution.
  operatorName: string;
}) {
  try {
    const contextLabel = actionTypeLabels[params.actionType];
    const noteDetail = `用户备注（非系统审计）｜关联操作：${contextLabel}｜${params.actionDetail}`.slice(0, 2000);
    await invokeWithAuth({
      url: '/api/v1/entities/operation_logs',
      method: 'POST',
      data: {
        customer_id: params.customerId || null,
        action_type: 'user_note',
        action_detail: noteDetail,
      },
    });
  } catch (err) {
    console.error('Failed to log operation:', err);
  }
}
