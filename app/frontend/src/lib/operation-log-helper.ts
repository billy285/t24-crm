import { client } from './api';
import { invokeWithAuth } from './tokenStore';

export type ActionType =
  | 'create_customer' | 'edit_customer' | 'delete_customer'
  | 'view_password'
  | 'create_follow_up' | 'edit_follow_up' | 'delete_follow_up'
  | 'create_media_account' | 'edit_media_account' | 'delete_media_account'
  | 'export_data'
  | 'create_deal' | 'edit_deal'
  | 'create_payment' | 'edit_payment' | 'delete_payment'
  | 'create_subscription' | 'edit_subscription' | 'delete_subscription'
  | 'create_customer_expense' | 'edit_customer_expense' | 'delete_customer_expense'
  | 'create_company_expense' | 'edit_company_expense' | 'delete_company_expense'
  | 'other';

export const actionTypeLabels: Record<string, string> = {
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
  export_data: '导出数据',
  create_deal: '新增成交',
  edit_deal: '编辑成交',
  create_payment: '新增收款',
  edit_payment: '编辑收款',
  delete_payment: '删除收款',
  create_subscription: '新增套餐续费',
  edit_subscription: '编辑套餐续费',
  delete_subscription: '删除套餐续费',
  create_customer_expense: '新增客户支出',
  edit_customer_expense: '编辑客户支出',
  delete_customer_expense: '删除客户支出',
  create_company_expense: '新增公司支出',
  edit_company_expense: '编辑公司支出',
  delete_company_expense: '删除公司支出',
  other: '其他操作',
};

export async function logOperation(params: {
  customerId?: number;
  actionType: ActionType;
  actionDetail: string;
  operatorName: string;
}) {
  try {
    const now = new Date().toISOString();
    await invokeWithAuth({
      url: '/api/v1/entities/operation_logs',
      method: 'POST',
      data: {
        customer_id: params.customerId || null,
        action_type: params.actionType,
        action_detail: params.actionDetail,
        operator_name: params.operatorName,
        ip_address: '',
        created_at: now,
      },
    });
  } catch (err) {
    console.error('Failed to log operation:', err);
  }
}
