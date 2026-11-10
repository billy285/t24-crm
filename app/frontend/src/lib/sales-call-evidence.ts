type Coverage = {
  status?: string;
  needs_retry?: boolean;
  unverified_ranges?: unknown[];
};

export type CallEvidence = {
  provider_calls: number;
  connection_status?: string;
  extension_number?: string | null;
  last_synced_at?: string | null;
  sync_coverage?: Coverage;
};

/** Positive records remain visible even when an employee must reconnect. */
export function callEvidenceState(item: CallEvidence) {
  const coverage = item.sync_coverage;
  const checkedWindow = item.connection_status === 'enabled' && Boolean(item.last_synced_at)
    && coverage?.status === 'window_fetched' && !coverage.needs_retry
    && Array.isArray(coverage.unverified_ranges) && coverage.unverified_ranges.length === 0;
  const available = item.provider_calls > 0 || checkedWindow;
  const pending = item.connection_status === 'disconnected' && !item.extension_number ? '待接入' : '待同步';
  return { available, label: available ? '已同步' : pending };
}

export function reportEvidenceState(report: { summary: { provider_calls: number }; employees: CallEvidence[] }) {
  const states = report.employees.map(callEvidenceState);
  const available = report.summary.provider_calls > 0 || states.length > 0 && states.every(state => state.available);
  return { available, label: available ? '已同步' : states.length > 0 && states.every(state => state.label === '待接入') ? '待接入' : '待同步' };
}
