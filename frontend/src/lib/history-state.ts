/** Pure mapping for persisted analysis history. It never runs or recomputes a method. */
import type { AnalysisHistoryItem, AnalysisJob, InputSnapshot, JobStatus, MethodId } from './contracts.ts';
import { sequenceSha256 } from './sequence.ts';

const CANONICAL_SEQUENCE = /^[ACDEFGHIKLMNPQRSTVWY]+$/;
const HISTORY_STATUSES = new Set<JobStatus>([
  'queued', 'running', 'success', 'partial_success', 'failed', 'interrupted',
  'unavailable', 'external_result_required',
]);
const METHODS = new Set<MethodId>(['lreca', 'fuzdrop', 'seg', 'dismeta']);

export interface HistoryQuery {
  limit: number;
  offset: number;
  status: JobStatus | '';
  method: MethodId | '';
}

export const DEFAULT_HISTORY_QUERY: HistoryQuery = { limit: 20, offset: 0, status: '', method: '' };

export function lastHistoryOffset(total: number, limit: number): number {
  if (!Number.isSafeInteger(total) || total <= 0 || !Number.isSafeInteger(limit) || limit <= 0) return 0;
  return Math.floor((total - 1) / limit) * limit;
}

export function normalizeHistoryQuery(value: Partial<HistoryQuery> = {}): HistoryQuery {
  const limit = Number.isSafeInteger(value.limit) ? Math.min(100, Math.max(1, value.limit!)) : DEFAULT_HISTORY_QUERY.limit;
  const offset = Number.isSafeInteger(value.offset) ? Math.max(0, value.offset!) : 0;
  const status = value.status && HISTORY_STATUSES.has(value.status) ? value.status : '';
  const method = value.method && METHODS.has(value.method) ? value.method : '';
  return { limit, offset, status, method };
}

export async function persistedInput(job: AnalysisJob): Promise<InputSnapshot | null> {
  const canonical = job.normalized_sequence;
  if (typeof canonical !== 'string' || canonical.length !== job.sequence.length
    || !CANONICAL_SEQUENCE.test(canonical)) return null;
  if (await sequenceSha256(canonical) !== job.sequence.sha256) return null;
  return {
    rawSequence: canonical,
    canonical,
    sequenceName: job.sequence.name,
    length: canonical.length,
    validResidues: canonical.length,
    // Persistence retains the canonical sequence, but cannot truthfully recover
    // whether the original submission used FASTA syntax or plain sequence text.
    inputType: 'persisted',
    submittedAt: job.created_at,
  };
}

export function historyPredictionSummary(item: AnalysisHistoryItem): string {
  const values: string[] = [];
  if (typeof item.lreca_score === 'number' && Number.isFinite(item.lreca_score)) values.push(`LRECA ${item.lreca_score.toFixed(3)}`);
  if (typeof item.fuzdrop_score === 'number' && Number.isFinite(item.fuzdrop_score)) values.push(`FuzDrop ${item.fuzdrop_score.toFixed(3)}`);
  if (typeof item.ensemble_score === 'number' && Number.isFinite(item.ensemble_score)) values.push(`Combined ${item.ensemble_score.toFixed(3)}`);
  return values.join(' · ') || 'No global score';
}

export function safeDownloadFilename(disposition: string | null, fallback: string): string {
  const safe = (value: string) => value.length > 0 && value.length <= 240
    && !/[\\/\u0000-\u001f\u007f]/.test(value) && value !== '.' && value !== '..';
  if (disposition && /^attachment(?:;|$)/i.test(disposition.trim())) {
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    if (encoded) {
      try { const decoded = decodeURIComponent(encoded); if (safe(decoded)) return decoded; } catch { /* invalid encoding */ }
    }
    const plain = /filename="([^"]+)"|filename=([^;\s]+)/i.exec(disposition);
    const candidate = plain?.[1] ?? plain?.[2];
    if (candidate && safe(candidate)) return candidate;
  }
  return safe(fallback) ? fallback : 'analysis-download';
}
