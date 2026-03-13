import { client } from './api';

export type ActionType =
  | 'create_customer' | 'edit_customer' | 'delete_customer'
  | 'view_password'
  | 'create_follow_up' | 'edit_follow_up' | 'delete_follow_up'
  | 'create_media_account' | 'edit_media_account' | 'delete_media_account'
  | 'export_data'
  | 'create_deal' | 'edit_deal'
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
    await client.entities.operation_logs.create({
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