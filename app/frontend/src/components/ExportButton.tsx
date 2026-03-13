import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Download, FileSpreadsheet, FileText } from 'lucide-react';
import { exportCSV, exportExcel } from '@/lib/export';
import { toast } from 'sonner';

interface ExportButtonProps {
  data: Record<string, any>[];
  columns: { key: string; label: string }[];
  filename: string;
  sheetName?: string;
}

export default function ExportButton({ data, columns, filename, sheetName }: ExportButtonProps) {
  const handleExport = (format: 'csv' | 'xlsx') => {
    if (data.length === 0) {
      toast.error('暂无数据可导出');
      return;
    }
    try {
      if (format === 'csv') {
        exportCSV({ data, columns, filename });
      } else {
        exportExcel({ data, columns, filename, sheetName });
      }
      toast.success(`已导出 ${data.length} 条数据为 ${format.toUpperCase()} 文件`);
    } catch (err) {
      toast.error('导出失败，请重试');
      console.error(err);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Download className="w-4 h-4" />
          导出
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => handleExport('xlsx')}>
          <FileSpreadsheet className="w-4 h-4 mr-2 text-green-600" />
          导出 Excel (.xlsx)
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleExport('csv')}>
          <FileText className="w-4 h-4 mr-2 text-blue-600" />
          导出 CSV (.csv)
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}