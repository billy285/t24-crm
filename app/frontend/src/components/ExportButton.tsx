import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Download, FileSpreadsheet, FileText } from 'lucide-react';
import { toast } from 'sonner';

interface ExportButtonProps {
  data: Record<string, any>[];
  columns: { key: string; label: string }[];
  filename: string;
  sheetName?: string;
}

export default function ExportButton({ data, columns, filename, sheetName }: ExportButtonProps) {
  const [exporting, setExporting] = useState(false);

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (data.length === 0) {
      toast.error('暂无数据可导出');
      return;
    }
    if (exporting) return;
    setExporting(true);
    try {
      // XLSX is intentionally loaded only after a desktop user chooses an
      // export format, keeping the large spreadsheet library out of mobile
      // customer and delivery route startup bundles.
      const { exportCSV, exportExcel } = await import('@/lib/export');
      if (format === 'csv') {
        exportCSV({ data, columns, filename });
      } else {
        exportExcel({ data, columns, filename, sheetName });
      }
      toast.success(`已导出 ${data.length} 条数据为 ${format.toUpperCase()} 文件`);
    } catch (err) {
      toast.error('导出失败，请重试');
      console.error(err);
    } finally {
      setExporting(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5" disabled={exporting}>
          <Download className="w-4 h-4" />
          {exporting ? '正在准备…' : '导出'}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => void handleExport('xlsx')}>
          <FileSpreadsheet className="w-4 h-4 mr-2 text-green-600" />
          导出 Excel (.xlsx)
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void handleExport('csv')}>
          <FileText className="w-4 h-4 mr-2 text-blue-600" />
          导出 CSV (.csv)
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
