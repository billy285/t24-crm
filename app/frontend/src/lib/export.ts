import * as XLSX from 'xlsx';
import { saveAs } from 'file-saver';

interface ExportOptions {
  data: Record<string, any>[];
  columns: { key: string; label: string }[];
  filename: string;
  sheetName?: string;
}

/**
 * Export data as CSV file
 */
export function exportCSV({ data, columns, filename }: ExportOptions) {
  const header = columns.map(c => c.label).join(',');
  const rows = data.map(row =>
    columns.map(c => {
      const val = row[c.key];
      if (val === null || val === undefined) return '';
      const str = String(val);
      // Escape commas and quotes
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    }).join(',')
  );
  // Add BOM for Chinese character support in Excel
  const bom = '\uFEFF';
  const csv = bom + [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  saveAs(blob, `${filename}.csv`);
}

/**
 * Export data as Excel (.xlsx) file
 */
export function exportExcel({ data, columns, filename, sheetName = 'Sheet1' }: ExportOptions) {
  const headerRow = columns.map(c => c.label);
  const dataRows = data.map(row =>
    columns.map(c => {
      const val = row[c.key];
      if (val === null || val === undefined) return '';
      return val;
    })
  );

  const ws = XLSX.utils.aoa_to_sheet([headerRow, ...dataRows]);

  // Set column widths based on content
  const colWidths = columns.map((c, i) => {
    const maxLen = Math.max(
      c.label.length * 2, // Chinese characters are wider
      ...dataRows.map(r => String(r[i] || '').length)
    );
    return { wch: Math.min(Math.max(maxLen + 2, 10), 40) };
  });
  ws['!cols'] = colWidths;

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName);

  const excelBuffer = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
  const blob = new Blob([excelBuffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  saveAs(blob, `${filename}.xlsx`);
}