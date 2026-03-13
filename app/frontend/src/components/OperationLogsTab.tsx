import { useState, useEffect } from 'react';
import { client } from '../lib/api';
import { actionTypeLabels } from '../lib/operation-log-helper';
import { Badge } from '@/components/ui/badge';
import {
  UserPlus, Edit, Trash2, Eye, MessageSquare, Share2, Download, FileText
} from 'lucide-react';

const actionIcons: Record<string, any> = {
  create_customer: UserPlus,
  edit_customer: Edit,
  delete_customer: Trash2,
  view_password: Eye,
  create_follow_up: MessageSquare,
  edit_follow_up: Edit,
  delete_follow_up: Trash2,
  create_media_account: Share2,
  edit_media_account: Edit,
  delete_media_account: Trash2,
  export_data: Download,
  other: FileText,
};

const actionColors: Record<string, string> = {
  create_customer: 'bg-green-100 text-green-700',
  edit_customer: 'bg-blue-100 text-blue-700',
  delete_customer: 'bg-red-100 text-red-700',
  view_password: 'bg-amber-100 text-amber-700',
  create_follow_up: 'bg-green-100 text-green-700',
  edit_follow_up: 'bg-blue-100 text-blue-700',
  delete_follow_up: 'bg-red-100 text-red-700',
  create_media_account: 'bg-green-100 text-green-700',
  edit_media_account: 'bg-blue-100 text-blue-700',
  delete_media_account: 'bg-red-100 text-red-700',
  export_data: 'bg-purple-100 text-purple-700',
  other: 'bg-slate-100 text-slate-600',
};

interface Props {
  customerId: number;
}

export default function OperationLogsTab({ customerId }: Props) {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLogs();
  }, [customerId]);

  const loadLogs = async () => {
    try {
      const res = await client.entities.operation_logs.query({
        query: { customer_id: customerId },
        sort: '-created_at',
        limit: 100,
      });
      setLogs(res?.data?.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-8"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" /></div>;
  }

  if (logs.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-8">暂无操作日志</p>;
  }

  return (
    <div className="space-y-3">
      {logs.map((log: any) => {
        const Icon = actionIcons[log.action_type] || FileText;
        const colorClass = actionColors[log.action_type] || 'bg-slate-100 text-slate-600';
        return (
          <div key={log.id} className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colorClass}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <Badge className={`text-xs ${colorClass}`}>
                  {actionTypeLabels[log.action_type] || log.action_type}
                </Badge>
                <span className="text-xs text-slate-500">{log.operator_name || '系统'}</span>
                <span className="text-xs text-slate-400 ml-auto">{log.created_at?.slice(0, 16).replace('T', ' ')}</span>
              </div>
              <p className="text-sm text-slate-600">{log.action_detail}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}