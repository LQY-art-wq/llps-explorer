'use client';

import { useState } from 'react';
import type {
  AnalysisExportKind, AnalysisHistoryItem, AnalysisHistoryPage, JobStatus, MethodId,
} from '../lib/contracts.ts';
import { DEFAULT_HISTORY_QUERY, historyPredictionSummary } from '../lib/history-state.ts';
import type { HistoryQuery } from '../lib/history-state.ts';
import { statusPresentation } from '../lib/viewer-data.ts';
import { Icon } from './icons';

interface AnalysisHistoryProps {
  page: AnalysisHistoryPage;
  query: HistoryQuery;
  loading: boolean;
  error: Error | null;
  action: string | null;
  retentionDays: number | null;
  currentJobId: string | null;
  onLoad: (query: Partial<HistoryQuery>) => Promise<void>;
  onOpen: (jobId: string) => Promise<boolean>;
  onDelete: (jobId: string) => Promise<boolean>;
  onDownload: (jobId: string, kind: AnalysisExportKind) => Promise<boolean>;
  onClose: () => void;
}

const STATUS_FILTERS: readonly { value: JobStatus | ''; label: string }[] = [
  { value: '', label: 'All statuses' }, { value: 'queued', label: 'Queued' }, { value: 'running', label: 'Running' },
  { value: 'success', label: 'Completed' }, { value: 'partial_success', label: 'Completed with warnings' },
  { value: 'failed', label: 'Failed' }, { value: 'interrupted', label: 'Interrupted' },
  { value: 'unavailable', label: 'Unavailable' }, { value: 'external_result_required', label: 'External result required' },
];
const METHOD_FILTERS: readonly { value: MethodId | ''; label: string }[] = [
  { value: '', label: 'All methods' }, { value: 'lreca', label: 'LRECA' },
  { value: 'fuzdrop', label: 'FuzDrop' }, { value: 'seg', label: 'SEG' },
  { value: 'dismeta', label: 'DisMeta' },
];
const DOWNLOADS: readonly { kind: AnalysisExportKind; label: string }[] = [
  { kind: 'json', label: 'Result JSON' }, { kind: 'summary.csv', label: 'Summary CSV' },
  { kind: 'residues.csv', label: 'Residues CSV' }, { kind: 'regions.csv', label: 'Regions CSV' },
  { kind: 'fasta', label: 'FASTA' },
];

function displayDate(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function HistoryActions({ item, current, action, onOpen, onDelete, onDownload, onClose }: {
  item: AnalysisHistoryItem; current: boolean; action: string | null;
  onOpen: AnalysisHistoryProps['onOpen']; onDelete: AnalysisHistoryProps['onDelete'];
  onDownload: AnalysisHistoryProps['onDownload']; onClose: AnalysisHistoryProps['onClose'];
}) {
  const busy = action !== null;
  async function open() { if (await onOpen(item.job_id)) onClose(); }
  async function remove() {
    if (!window.confirm('This permanently deletes the stored sequence and analysis result.')) return;
    if (await onDelete(item.job_id) && current) onClose();
  }
  return <div className="history-actions">
    <button className="button primary" type="button" disabled={busy} onClick={() => void open()}>Open</button>
    <details className="download-menu">
      <summary className="button" aria-label={`Download ${item.sequence_name || 'unnamed protein'} analysis`}>Download</summary>
      <div className="download-menu-list">
        {DOWNLOADS.map(({ kind, label }) => <button key={kind} type="button" disabled={busy}
          onClick={() => void onDownload(item.job_id, kind)}>{label}</button>)}
      </div>
    </details>
    <button className="button danger-button" type="button" disabled={busy} onClick={() => void remove()}>Delete</button>
  </div>;
}

export function AnalysisHistory(props: AnalysisHistoryProps) {
  const [status, setStatus] = useState<JobStatus | ''>(props.query.status);
  const [method, setMethod] = useState<MethodId | ''>(props.query.method);
  const filterQuery = (): HistoryQuery => ({ ...DEFAULT_HISTORY_QUERY, offset: 0, status, method });
  const pageQuery = (offset: number): HistoryQuery => ({ ...props.query, offset });
  const canPrevious = props.page.offset > 0;
  const canNext = props.page.offset + props.page.items.length < props.page.total;
  return <section className="history-panel" aria-label="Saved analysis history">
    <p className="privacy-note">
      {props.retentionDays === null ? 'Analysis retention details are temporarily unavailable.'
        : `Analyses are retained for ${props.retentionDays} days.`}
      {' '}You can permanently delete a stored sequence and its result at any time.
    </p>
    <div className="history-toolbar">
      <label>Status<select value={status} onChange={(event) => setStatus(event.target.value as JobStatus | '')}>
        {STATUS_FILTERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>
      <label>Method<select value={method} onChange={(event) => setMethod(event.target.value as MethodId | '')}>
        {METHOD_FILTERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>
      <button className="button" type="button" disabled={props.loading} onClick={() => void props.onLoad(filterQuery())}>
        <Icon name="refresh" width="14" height="14" /> Apply filters
      </button>
    </div>
    {props.error && <div className="notice error-notice" role="alert"><strong>{props.error.message}</strong></div>}
    {props.loading && !props.page.items.length ? <p className="muted" role="status">Loading saved analyses…</p>
      : !props.page.items.length ? <div className="empty-state history-empty"><Icon name="history" width="28" height="28" />
        <h3>No saved analyses yet.</h3><p>Analyses created by this anonymous browser profile will appear here.</p></div>
        : <div className="history-table-wrap"><table className="data-table history-table">
          <caption className="sr-only">Saved analyses belonging to this anonymous browser session.</caption>
          <thead><tr><th scope="col">Sequence</th><th scope="col">Date</th><th scope="col">Methods</th>
            <th scope="col">Status</th><th scope="col">Prediction summary</th><th scope="col">Expires</th><th scope="col">Actions</th></tr></thead>
          <tbody>{props.page.items.map((item) => {
            const statusView = statusPresentation(item.status);
            return <tr key={item.job_id} data-current={props.currentJobId === item.job_id || undefined}>
              <td><strong>{item.sequence_name || 'Unnamed protein'}</strong><small>{item.sequence_length.toLocaleString()} aa</small></td>
              <td><time dateTime={item.created_at}>{displayDate(item.created_at)}</time></td>
              <td>{item.selected_methods.map((value) => value.toUpperCase()).join(' + ')}</td>
              <td><span className="badge" data-tone={statusView.tone}>{statusView.label}</span></td>
              <td>{historyPredictionSummary(item)}</td>
              <td><time dateTime={item.expires_at}>{displayDate(item.expires_at)}</time></td>
              <td><HistoryActions item={item} current={props.currentJobId === item.job_id} action={props.action}
                onOpen={props.onOpen} onDelete={props.onDelete} onDownload={props.onDownload} onClose={props.onClose} /></td>
            </tr>;
          })}</tbody>
        </table></div>}
    <div className="history-pagination">
      <span className="muted" aria-live="polite">{props.page.total ? `${props.page.offset + 1}–${props.page.offset + props.page.items.length} of ${props.page.total}` : '0 saved analyses'}</span>
      <div className="button-group"><button className="button" type="button" disabled={!canPrevious || props.loading}
        onClick={() => void props.onLoad(pageQuery(Math.max(0, props.page.offset - props.page.limit)))}>Previous</button>
        <button className="button" type="button" disabled={!canNext || props.loading}
          onClick={() => void props.onLoad(pageQuery(props.page.offset + props.page.limit))}>Next</button></div>
    </div>
  </section>;
}
