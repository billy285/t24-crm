/** Describes the existing sales access rules; it does not grant permissions. */
export default function SalesDataScopeHint({ role }: { role: string }) {
  const scope = role === 'super_admin' || role === 'admin'
    ? { title: '全部电话销售任务', detail: '可切换销售，查看其电话任务与线索。' }
    : role === 'sales_manager'
      ? { title: '直属销售任务及所管理的线索', detail: '按直属上级和线索管理范围查看，不代表全公司销售数据。' }
      : role === 'sales'
        ? { title: '本人负责的电话任务', detail: '受邀商家档案按只读或协作授权查看；邀请不开放他人的拨号任务。' }
        : role === 'sales_partner'
          ? { title: '不开放电话销售任务', detail: '渠道账号使用本人归属客户与分润入口。' }
          : { title: '不开放电话销售任务', detail: '客户资料、财务等页面仍按各自现有授权控制。' };

  return <aside aria-label="销售数据范围说明" className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-slate-600">
    <p className="font-medium text-slate-800">销售数据范围：{scope.title}</p>
    <p className="mt-1">{scope.detail}</p>
    <p className="mt-1">部门和岗位用于组织归属，不决定销售数据范围。</p>
  </aside>;
}
