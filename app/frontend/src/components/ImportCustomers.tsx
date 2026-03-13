import { useState, useRef, useCallback } from 'react';
import * as XLSX from 'xlsx';
import { client } from '../lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { toast } from 'sonner';
import { Upload, FileSpreadsheet, CheckCircle2, XCircle, AlertTriangle, Download } from 'lucide-react';

// Column mapping: Chinese header -> field key
const HEADER_MAP: Record<string, string> = {
  '商家名称': 'business_name',
  '联系人': 'contact_name',
  '电话': 'phone',
  '微信': 'wechat',
  '邮箱': 'email',
  '行业': 'industry',
  '地址': 'address',
  '城市': 'city',
  '州': 'state',
  '客户来源': 'source',
  '客户等级': 'level',
  '客户状态': 'status',
  '负责销售': 'sales_person',
  '当前平台': 'current_platform',
  '月订单量': 'monthly_orders',
  '已有点餐系统': 'has_ordering_system',
  '官网': 'website',
  '备注': 'notes',
};

const INDUSTRY_REVERSE: Record<string, string> = {
  '餐厅': 'restaurant', '美甲': 'nail', '按摩': 'massage', '美容': 'beauty', '超市': 'supermarket', '其他': 'other',
};
const SOURCE_REVERSE: Record<string, string> = {
  '电话销售': 'phone', '转介绍': 'referral', '广告': 'ads', '私域': 'private', '老客户': 'returning', '其他': 'other',
};
const LEVEL_REVERSE: Record<string, string> = {
  '高意向': 'high', '普通': 'normal', '低意向': 'low', 'VIP': 'vip',
};
const STATUS_REVERSE: Record<string, string> = {
  '新线索': 'new', '跟进中': 'following', '已成交': 'closed', '暂停': 'paused', '流失': 'lost',
};

interface ParsedRow {
  rowIndex: number;
  data: Record<string, any>;
  errors: string[];
  isDuplicate: boolean;
  duplicateField?: string;
}

interface ImportResult {
  success: number;
  failed: number;
  skipped: number;
  errors: { row: number; reason: string }[];
}

interface ImportCustomersProps {
  existingCustomers: any[];
  onImportComplete: () => void;
}

export default function ImportCustomers({ existingCustomers, onImportComplete }: ImportCustomersProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<'upload' | 'preview' | 'importing' | 'result'>('upload');
  const [parsedRows, setParsedRows] = useState<ParsedRow[]>([]);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [progress, setProgress] = useState(0);
  const [fileName, setFileName] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setStep('upload');
    setParsedRows([]);
    setImportResult(null);
    setProgress(0);
    setFileName('');
  };

  const handleOpen = () => {
    reset();
    setOpen(true);
  };

  const downloadTemplate = () => {
    const headers = Object.keys(HEADER_MAP);
    const exampleRow = [
      'ABC餐厅', '张三', '626-123-4567', 'zhangsan_wx', 'zhang@email.com',
      '餐厅', '123 Main St', 'Alhambra', 'CA', '电话销售', '普通', '新线索',
      '李四', '无', '100', '否', 'www.abc.com', '潜在大客户',
    ];
    const ws = XLSX.utils.aoa_to_sheet([headers, exampleRow]);
    ws['!cols'] = headers.map(h => ({ wch: Math.max(h.length * 2 + 2, 12) }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, '客户导入模板');
    XLSX.writeFile(wb, '客户导入模板.xlsx');
  };

  const parseFile = useCallback((file: File) => {
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target?.result as ArrayBuffer);
        const workbook = XLSX.read(data, { type: 'array' });
        const sheetName = workbook.SheetNames[0];
        const sheet = workbook.Sheets[sheetName];
        const jsonData = XLSX.utils.sheet_to_json<Record<string, any>>(sheet, { defval: '' });

        if (jsonData.length === 0) {
          toast.error('文件中没有数据');
          return;
        }

        // Build existing phone/business_name sets for duplicate detection
        const existingPhones = new Set(existingCustomers.map(c => c.phone?.trim()).filter(Boolean));
        const existingNames = new Set(existingCustomers.map(c => c.business_name?.trim()).filter(Boolean));

        // Also track duplicates within the file itself
        const filePhones = new Set<string>();
        const fileNames = new Set<string>();

        const rows: ParsedRow[] = jsonData.map((row, idx) => {
          const errors: string[] = [];
          const mapped: Record<string, any> = {};

          // Map headers to fields
          for (const [header, value] of Object.entries(row)) {
            const fieldKey = HEADER_MAP[header.trim()];
            if (fieldKey) {
              mapped[fieldKey] = String(value).trim();
            }
          }

          // Validate required fields
          if (!mapped.business_name) errors.push('缺少商家名称');
          if (!mapped.contact_name) errors.push('缺少联系人');
          if (!mapped.phone) errors.push('缺少电话');

          // Convert Chinese labels to enum values
          if (mapped.industry) {
            mapped.industry = INDUSTRY_REVERSE[mapped.industry] || mapped.industry;
            if (!['restaurant', 'nail', 'massage', 'beauty', 'supermarket', 'other'].includes(mapped.industry)) {
              mapped.industry = 'other';
            }
          } else {
            mapped.industry = 'restaurant';
          }

          if (mapped.source) {
            mapped.source = SOURCE_REVERSE[mapped.source] || mapped.source;
            if (!['phone', 'referral', 'ads', 'private', 'returning', 'other'].includes(mapped.source)) {
              mapped.source = 'phone';
            }
          } else {
            mapped.source = 'phone';
          }

          if (mapped.level) {
            mapped.level = LEVEL_REVERSE[mapped.level] || mapped.level;
            if (!['high', 'normal', 'low', 'vip'].includes(mapped.level)) {
              mapped.level = 'normal';
            }
          } else {
            mapped.level = 'normal';
          }

          if (mapped.status) {
            mapped.status = STATUS_REVERSE[mapped.status] || mapped.status;
            if (!['new', 'following', 'closed', 'paused', 'lost'].includes(mapped.status)) {
              mapped.status = 'new';
            }
          } else {
            mapped.status = 'new';
          }

          // Convert boolean
          mapped.has_ordering_system = ['是', 'true', '1', 'yes'].includes(
            String(mapped.has_ordering_system || '').toLowerCase()
          );

          // Convert number
          mapped.monthly_orders = parseInt(String(mapped.monthly_orders || '0'), 10) || 0;

          // Set defaults
          if (!mapped.state) mapped.state = 'CA';
          if (!mapped.current_platform) mapped.current_platform = '无';

          // Duplicate detection against existing data
          let isDuplicate = false;
          let duplicateField = '';
          const phone = mapped.phone?.trim();
          const name = mapped.business_name?.trim();

          if (phone && existingPhones.has(phone)) {
            isDuplicate = true;
            duplicateField = `电话 "${phone}" 已存在`;
          } else if (name && existingNames.has(name)) {
            isDuplicate = true;
            duplicateField = `商家名称 "${name}" 已存在`;
          }

          // Duplicate detection within file
          if (!isDuplicate && phone) {
            if (filePhones.has(phone)) {
              isDuplicate = true;
              duplicateField = `文件内电话 "${phone}" 重复`;
            }
          }
          if (!isDuplicate && name) {
            if (fileNames.has(name)) {
              isDuplicate = true;
              duplicateField = `文件内商家名称 "${name}" 重复`;
            }
          }

          if (phone) filePhones.add(phone);
          if (name) fileNames.add(name);

          return {
            rowIndex: idx + 2, // Excel row (1-indexed header + 1-indexed data)
            data: mapped,
            errors,
            isDuplicate,
            duplicateField,
          };
        });

        setParsedRows(rows);
        setStep('preview');
      } catch (err) {
        console.error(err);
        toast.error('文件解析失败，请检查文件格式');
      }
    };
    reader.readAsArrayBuffer(file);
  }, [existingCustomers]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) parseFile(file);
    // Reset input so same file can be selected again
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (['csv', 'xlsx', 'xls'].includes(ext || '')) {
        parseFile(file);
      } else {
        toast.error('请上传 CSV 或 Excel 文件');
      }
    }
  };

  const validRows = parsedRows.filter(r => r.errors.length === 0 && !r.isDuplicate);
  const errorRows = parsedRows.filter(r => r.errors.length > 0);
  const duplicateRows = parsedRows.filter(r => r.isDuplicate && r.errors.length === 0);

  const handleImport = async () => {
    if (validRows.length === 0) {
      toast.error('没有可导入的有效数据');
      return;
    }

    setStep('importing');
    setProgress(0);

    const result: ImportResult = { success: 0, failed: 0, skipped: duplicateRows.length + errorRows.length, errors: [] };
    const total = validRows.length;
    const baseCode = existingCustomers.length;

    for (let i = 0; i < validRows.length; i++) {
      const row = validRows[i];
      try {
        const now = new Date().toISOString();
        const code = `C${new Date().getFullYear()}${String(baseCode + i + 1).padStart(4, '0')}`;
        await client.entities.customers.create({
          data: {
            ...row.data,
            customer_code: code,
            created_at: now,
            updated_at: now,
          },
        });
        result.success++;
      } catch (err: any) {
        result.failed++;
        result.errors.push({
          row: row.rowIndex,
          reason: err?.message || '创建失败',
        });
      }
      setProgress(Math.round(((i + 1) / total) * 100));
    }

    setImportResult(result);
    setStep('result');

    if (result.success > 0) {
      onImportComplete();
    }
  };

  return (
    <>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={handleOpen}>
        <Upload className="w-4 h-4" />
        导入
      </Button>

      <Dialog open={open} onOpenChange={(v) => { if (!v && step !== 'importing') { setOpen(false); } }}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {step === 'upload' && '批量导入客户'}
              {step === 'preview' && '数据预览与校验'}
              {step === 'importing' && '正在导入...'}
              {step === 'result' && '导入完成'}
            </DialogTitle>
          </DialogHeader>

          {/* Step 1: Upload */}
          {step === 'upload' && (
            <div className="space-y-4">
              <div
                className="border-2 border-dashed border-slate-300 rounded-lg p-8 text-center hover:border-blue-400 transition-colors cursor-pointer"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
              >
                <FileSpreadsheet className="w-12 h-12 mx-auto text-slate-400 mb-3" />
                <p className="text-sm text-slate-600 mb-1">点击或拖拽文件到此处上传</p>
                <p className="text-xs text-slate-400">支持 .xlsx, .xls, .csv 格式</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h4 className="text-sm font-medium text-blue-800 mb-2">📋 导入说明</h4>
                <ul className="text-xs text-blue-700 space-y-1">
                  <li>• 必填字段：<strong>商家名称</strong>、<strong>联系人</strong>、<strong>电话</strong></li>
                  <li>• 行业可填：餐厅、美甲、按摩、美容、超市、其他</li>
                  <li>• 客户来源可填：电话销售、转介绍、广告、私域、老客户、其他</li>
                  <li>• 客户等级可填：高意向、普通、低意向、VIP</li>
                  <li>• 客户状态可填：新线索、跟进中、已成交、暂停、流失</li>
                  <li>• 系统将自动检测重复数据（按电话和商家名称）</li>
                </ul>
              </div>

              <Button variant="outline" size="sm" onClick={downloadTemplate} className="gap-1.5">
                <Download className="w-4 h-4" />
                下载导入模板
              </Button>
            </div>
          )}

          {/* Step 2: Preview */}
          {step === 'preview' && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <FileSpreadsheet className="w-4 h-4" />
                <span>{fileName}</span>
                <span className="text-slate-400">|</span>
                <span>共 {parsedRows.length} 条数据</span>
              </div>

              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                  <CheckCircle2 className="w-5 h-5 mx-auto text-green-600 mb-1" />
                  <p className="text-lg font-bold text-green-700">{validRows.length}</p>
                  <p className="text-xs text-green-600">可导入</p>
                </div>
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-center">
                  <AlertTriangle className="w-5 h-5 mx-auto text-amber-600 mb-1" />
                  <p className="text-lg font-bold text-amber-700">{duplicateRows.length}</p>
                  <p className="text-xs text-amber-600">重复（跳过）</p>
                </div>
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-center">
                  <XCircle className="w-5 h-5 mx-auto text-red-600 mb-1" />
                  <p className="text-lg font-bold text-red-700">{errorRows.length}</p>
                  <p className="text-xs text-red-600">校验失败</p>
                </div>
              </div>

              {/* Data preview table */}
              <div className="border rounded-lg overflow-hidden">
                <div className="max-h-[300px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-slate-100">
                      <tr>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">行</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">状态</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">商家名称</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">联系人</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">电话</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">城市</th>
                        <th className="px-2 py-2 text-left font-medium text-slate-500">问题</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parsedRows.map((row, i) => (
                        <tr
                          key={i}
                          className={`border-t ${
                            row.errors.length > 0
                              ? 'bg-red-50'
                              : row.isDuplicate
                              ? 'bg-amber-50'
                              : 'hover:bg-slate-50'
                          }`}
                        >
                          <td className="px-2 py-1.5 text-slate-400">{row.rowIndex}</td>
                          <td className="px-2 py-1.5">
                            {row.errors.length > 0 ? (
                              <Badge className="bg-red-100 text-red-700 text-[10px]">错误</Badge>
                            ) : row.isDuplicate ? (
                              <Badge className="bg-amber-100 text-amber-700 text-[10px]">重复</Badge>
                            ) : (
                              <Badge className="bg-green-100 text-green-700 text-[10px]">有效</Badge>
                            )}
                          </td>
                          <td className="px-2 py-1.5">{row.data.business_name || '-'}</td>
                          <td className="px-2 py-1.5">{row.data.contact_name || '-'}</td>
                          <td className="px-2 py-1.5">{row.data.phone || '-'}</td>
                          <td className="px-2 py-1.5">{row.data.city || '-'}</td>
                          <td className="px-2 py-1.5 text-red-600">
                            {row.errors.length > 0
                              ? row.errors.join('; ')
                              : row.isDuplicate
                              ? row.duplicateField
                              : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="flex justify-between items-center">
                <Button variant="outline" size="sm" onClick={reset}>
                  重新选择文件
                </Button>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
                    取消
                  </Button>
                  <Button
                    size="sm"
                    className="bg-blue-600 hover:bg-blue-700"
                    disabled={validRows.length === 0}
                    onClick={handleImport}
                  >
                    确认导入 {validRows.length} 条数据
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Importing */}
          {step === 'importing' && (
            <div className="space-y-4 py-4">
              <div className="text-center">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto mb-4" />
                <p className="text-sm text-slate-600 mb-2">正在导入客户数据...</p>
                <p className="text-xs text-slate-400">请勿关闭此窗口</p>
              </div>
              <Progress value={progress} className="h-2" />
              <p className="text-center text-xs text-slate-500">{progress}%</p>
            </div>
          )}

          {/* Step 4: Result */}
          {step === 'result' && importResult && (
            <div className="space-y-4">
              <div className="text-center py-2">
                {importResult.success > 0 ? (
                  <CheckCircle2 className="w-12 h-12 mx-auto text-green-500 mb-2" />
                ) : (
                  <XCircle className="w-12 h-12 mx-auto text-red-500 mb-2" />
                )}
                <h3 className="text-lg font-semibold text-slate-800">导入完成</h3>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-green-700">{importResult.success}</p>
                  <p className="text-xs text-green-600">成功导入</p>
                </div>
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-amber-700">{importResult.skipped}</p>
                  <p className="text-xs text-amber-600">跳过（重复/错误）</p>
                </div>
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-red-700">{importResult.failed}</p>
                  <p className="text-xs text-red-600">导入失败</p>
                </div>
              </div>

              {importResult.errors.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                  <h4 className="text-sm font-medium text-red-800 mb-2">失败详情</h4>
                  <ul className="text-xs text-red-700 space-y-1 max-h-[120px] overflow-y-auto">
                    {importResult.errors.map((e, i) => (
                      <li key={i}>第 {e.row} 行: {e.reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-end">
                <Button size="sm" onClick={() => { setOpen(false); reset(); }} className="bg-blue-600 hover:bg-blue-700">
                  完成
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}