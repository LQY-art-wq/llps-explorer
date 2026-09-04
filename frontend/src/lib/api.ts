import type {
  AnalysisExportKind, AnalysisHistoryItem, AnalysisHistoryPage, AnalysisJob, AnalysisRequest,
  FuzDropImportRequest, FuzDropImportResponse, MethodDescriptor, PublicConfig,
} from './contracts.ts';
import { isTerminalJob } from './analysis-state.ts';
import { normalizeHistoryQuery, safeDownloadFilename } from './history-state.ts';
import type { HistoryQuery } from './history-state.ts';

const MESSAGES: Record<string, string> = {
  INVALID_AMINO_ACID: 'The sequence contains an unsupported residue. Check the highlighted input error.',
  INVALID_SEQUENCE_TYPE: 'Enter a protein sequence as text.', EMPTY_SEQUENCE: 'Enter a protein sequence.',
  INVALID_FASTA: 'Check the FASTA header and sequence.', MULTIPLE_FASTA_RECORDS: 'Enter exactly one protein sequence.',
  INVALID_SEQUENCE_NAME: 'Use a sequence name of at most 128 characters without control characters.',
  EMPTY_SELECTED_METHODS: 'Select at least one available method.', UNKNOWN_METHOD: 'A selected method is unsupported.',
  DUPLICATE_SELECTED_METHODS: 'Select each method only once.', INVALID_ANALYSIS_REQUEST: 'Check the analysis input and options.',
  INVALID_ENSEMBLE_WEIGHTS: 'Prediction weights must be valid numbers that total 100%.',
  INVALID_ENSEMBLE_METHOD: 'Only LRECA and FuzDrop can have prediction weights.',
  WEIGHTED_MODE_REQUIRES_LRECA_AND_FUZDROP: 'Weighted mode requires LRECA and an enabled FuzDrop import.',
  INVALID_EXTERNAL_RESULT_METHOD: 'Only FuzDrop accepts imported results.',
  EXTERNAL_RESULT_METHOD_NOT_SELECTED: 'Enable the imported FuzDrop result for this analysis.',
  EXTERNAL_RESULT_NOT_FOUND: 'The imported result is missing or expired. Import it again.',
  EXTERNAL_RESULT_SEQUENCE_MISMATCH: 'The imported FuzDrop result does not match this sequence.',
  EXTERNAL_RESULT_STORE_FULL: 'The import store is full. Try again after older results expire.',
  EXTERNAL_RESULT_INVALID: 'The imported result could not be validated. Import it again.',
  ANALYSIS_CAPACITY_EXCEEDED: 'The analysis service is busy. Try again shortly.',
  ANALYSIS_JOB_NOT_FOUND: 'This job is unavailable or expired. Start a new analysis if needed.',
  ANALYSIS_INTERRUPTED: 'This analysis stopped when the service restarted. Start a new analysis if needed.',
  ANALYSIS_NOT_READY_FOR_EXPORT: 'This analysis is still running. Download it after the analysis finishes.',
  ANALYSIS_UNAVAILABLE: 'The analysis service is unavailable. Try again shortly.',
  FUZDROP_IMPORT_DISABLED: 'FuzDrop import is currently disabled by the service.',
  FUZDROP_IMPORT_TOO_LARGE: 'The import exceeds the service size limit. Use a smaller official export.',
  FUZDROP_INVALID_IMPORT_REQUEST: 'Check the import fields and required declarations.',
  FUZDROP_INVALID_SEQUENCE: 'Correct the current protein sequence before importing.',
  FUZDROP_SEQUENCE_MISMATCH: 'The imported FuzDrop result does not match the current sequence.',
  FUZDROP_RESIDUE_COUNT_MISMATCH: 'The imported residue count does not match the current sequence.',
  FUZDROP_INVALID_COORDINATE: 'The imported regions contain invalid sequence coordinates.',
  FUZDROP_INVALID_REGION_TYPE: 'Use the region labels from the official FuzDrop export.',
  FUZDROP_INVALID_NUMERIC_VALUE: 'The import contains an invalid numeric value.',
  FUZDROP_SCORE_OUT_OF_RANGE: 'FuzDrop probability scores must be between zero and one.',
  FUZDROP_SCHEMA_CHANGED: 'The export headers do not match the supported official format.',
  FUZDROP_PARSE_ERROR: 'The export could not be parsed. Check the original tab-separated format.',
  FUZDROP_INVALID_TEXT_ENCODING: 'Use a UTF-8 text export.',
  FUZDROP_PROGRAMMATIC_ACCESS_UNAVAILABLE: 'Automatic FuzDrop prediction is unavailable. Import an official result.',
  NETWORK_ERROR: 'Could not reach the analysis service. Check the connection and retry.',
  INVALID_RESPONSE: 'The service returned an unexpected response. Retry or check service availability.',
  REQUEST_TOO_LARGE: 'The request exceeds the 5 MiB workspace limit. Reduce the import size and try again.',
  INVALID_CONTENT_TYPE: 'The request must use JSON. Retry from the analysis workspace.',
  INVALID_REQUEST_ORIGIN: 'Submit the request from this same workspace, then try again.',
  API_ROUTE_NOT_FOUND: 'This API operation is not available in the current workspace.',
  REQUEST_FAILED: 'The request could not be completed. Check the input and retry.',
  INVALID_DRAFT: 'Check the sequence and analysis selections before running.',
};
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(code: string, status = 0) {
    const safeCode = Object.hasOwn(MESSAGES, code) ? code : 'REQUEST_FAILED';
    super(MESSAGES[safeCode]);
    this.name = 'ApiError'; this.code = safeCode; this.status = status;
  }
}
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}
export function friendlyApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError('NETWORK_ERROR');
}
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
async function fetchResponse(
  path: string, method: 'GET' | 'POST' | 'DELETE', body: unknown, signal?: AbortSignal, accept = 'application/json',
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { method, signal, cache: 'no-store',
      credentials: 'same-origin',
      headers: body === undefined ? { Accept: accept } : { Accept: accept, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  } catch (error) {
    if (signal?.aborted || isAbortError(error)) throw new DOMException('Request cancelled.', 'AbortError');
    throw new ApiError('NETWORK_ERROR');
  }
  if (response.ok) return response;
  let payload: unknown = null;
  try { payload = await response.json(); }
  catch (error) {
    if (signal?.aborted || isAbortError(error)) throw new DOMException('Request cancelled.', 'AbortError');
    throw new ApiError(response.ok ? 'INVALID_RESPONSE' : 'REQUEST_FAILED', response.status);
  }
  const detail = object(payload) && object(payload.detail) ? payload.detail : payload;
  const code = object(detail) && typeof detail.code === 'string' ? detail.code : 'REQUEST_FAILED';
  throw new ApiError(code, response.status);
}
async function request(path: string, method: 'GET' | 'POST', body: unknown, signal?: AbortSignal): Promise<unknown> {
  const response = await fetchResponse(path, method, body, signal);
  try { return await response.json(); }
  catch (error) {
    if (signal?.aborted || isAbortError(error)) throw new DOMException('Request cancelled.', 'AbortError');
    throw new ApiError('INVALID_RESPONSE', response.status);
  }
}
const METHODS = new Set(['lreca', 'fuzdrop', 'seg', 'dismeta']);
const STATUSES = new Set(['queued', 'running', 'success', 'partial_success', 'failed', 'interrupted', 'unavailable', 'external_result_required']);
function analysisJob(value: unknown): AnalysisJob {
  if (!object(value) || typeof value.job_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.job_id)
    || !STATUSES.has(String(value.status)) || !object(value.methods) || !object(value.sequence)
    || value.result_schema_version !== '1.0'
    || typeof value.sequence.length !== 'number' || !Number.isSafeInteger(value.sequence.length) || value.sequence.length < 1
    || typeof value.sequence.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.sequence.sha256)
    || (value.sequence.name !== null && typeof value.sequence.name !== 'string')
    || (value.normalized_sequence !== undefined && value.normalized_sequence !== null
      && typeof value.normalized_sequence !== 'string')
    || !Array.isArray(value.selected_methods) || value.selected_methods.some((id) => !METHODS.has(String(id)))) throw new ApiError('INVALID_RESPONSE');
  return value as unknown as AnalysisJob;
}
export async function getMethods(signal?: AbortSignal): Promise<MethodDescriptor[]> {
  const value = await request('/methods', 'GET', undefined, signal);
  if (!object(value) || !Array.isArray(value.methods) || value.methods.some((row) => !object(row)
    || !METHODS.has(String(row.id)) || typeof row.automatic_analysis_available !== 'boolean'
    || typeof row.manual_import_available !== 'boolean')) throw new ApiError('INVALID_RESPONSE');
  return value.methods as MethodDescriptor[];
}
export async function submitAnalysis(payload: AnalysisRequest, signal?: AbortSignal): Promise<AnalysisJob> {
  return analysisJob(await request('/analysis', 'POST', payload, signal));
}
export async function getAnalysis(jobId: string, signal?: AbortSignal): Promise<AnalysisJob> {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) throw new ApiError('ANALYSIS_JOB_NOT_FOUND', 404);
  const value = analysisJob(await request(`/analysis/${encodeURIComponent(jobId)}`, 'GET', undefined, signal));
  if (value.job_id !== jobId) throw new ApiError('INVALID_RESPONSE');
  return value;
}
function historyItem(value: unknown): AnalysisHistoryItem {
  if (!object(value) || typeof value.job_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.job_id)
    || typeof value.sequence_length !== 'number' || !Number.isSafeInteger(value.sequence_length) || value.sequence_length < 1
    || (value.sequence_name !== null && typeof value.sequence_name !== 'string')
    || !STATUSES.has(String(value.status)) || !Array.isArray(value.selected_methods)
    || value.selected_methods.some((id) => !METHODS.has(String(id)))
    || (value.prediction_mode !== 'independent' && value.prediction_mode !== 'weighted')
    || typeof value.created_at !== 'string' || typeof value.updated_at !== 'string'
    || typeof value.expires_at !== 'string' || value.result_schema_version !== '1.0') {
    throw new ApiError('INVALID_RESPONSE');
  }
  for (const key of ['lreca_score', 'fuzdrop_score', 'ensemble_score'] as const) {
    const score = value[key];
    if (score !== null && (typeof score !== 'number' || !Number.isFinite(score))) throw new ApiError('INVALID_RESPONSE');
  }
  return value as unknown as AnalysisHistoryItem;
}
export async function listAnalysisHistory(query: Partial<HistoryQuery> = {}, signal?: AbortSignal): Promise<AnalysisHistoryPage> {
  const normalized = normalizeHistoryQuery(query);
  const search = new URLSearchParams({ limit: String(normalized.limit), offset: String(normalized.offset) });
  if (normalized.status) search.set('status', normalized.status);
  if (normalized.method) search.set('method', normalized.method);
  const value = await request(`/analysis/history?${search}`, 'GET', undefined, signal);
  if (!object(value) || !Array.isArray(value.items) || !Number.isSafeInteger(value.total) || Number(value.total) < 0
    || value.limit !== normalized.limit || value.offset !== normalized.offset) throw new ApiError('INVALID_RESPONSE');
  return { ...value, items: value.items.map(historyItem) } as AnalysisHistoryPage;
}
export async function deleteAnalysis(jobId: string, signal?: AbortSignal): Promise<void> {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) throw new ApiError('ANALYSIS_JOB_NOT_FOUND', 404);
  const response = await fetchResponse(`/analysis/${encodeURIComponent(jobId)}`, 'DELETE', undefined, signal);
  if (response.status !== 204) throw new ApiError('INVALID_RESPONSE', response.status);
}
export async function getPublicConfig(signal?: AbortSignal): Promise<PublicConfig> {
  const value = await request('/config/public', 'GET', undefined, signal);
  if (!object(value) || !Number.isSafeInteger(value.analysis_retention_days)
    || Number(value.analysis_retention_days) < 1) throw new ApiError('INVALID_RESPONSE');
  return value as unknown as PublicConfig;
}

const EXPORTS: Record<AnalysisExportKind, { accept: string; extension: string }> = {
  json: { accept: 'application/json', extension: 'json' },
  'summary.csv': { accept: 'text/csv', extension: 'csv' },
  'residues.csv': { accept: 'text/csv', extension: 'csv' },
  'regions.csv': { accept: 'text/csv', extension: 'csv' },
  fasta: { accept: 'text/plain', extension: 'fasta' },
};
export interface AnalysisDownload { blob: Blob; filename: string; contentType: string }
export async function getAnalysisExport(jobId: string, kind: AnalysisExportKind, signal?: AbortSignal): Promise<AnalysisDownload> {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) throw new ApiError('ANALYSIS_JOB_NOT_FOUND', 404);
  const format = EXPORTS[kind];
  const response = await fetchResponse(`/analysis/${encodeURIComponent(jobId)}/export/${kind}`, 'GET', undefined, signal, format.accept);
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.startsWith(format.accept)) throw new ApiError('INVALID_RESPONSE', response.status);
  const filename = safeDownloadFilename(response.headers.get('content-disposition'), `analysis_${jobId}.${format.extension}`);
  return { blob: await response.blob(), filename, contentType };
}
export async function importFuzDrop(payload: FuzDropImportRequest, signal?: AbortSignal): Promise<FuzDropImportResponse> {
  const value = await request('/methods/fuzdrop/import', 'POST', payload, signal);
  if (!object(value) || value.method !== 'fuzdrop' || value.status !== 'success' || value.validation_status !== 'valid'
    || typeof value.result_id !== 'string' || typeof value.sequence !== 'string'
    || typeof value.sequence_sha256 !== 'string' || typeof value.expires_at !== 'string') throw new ApiError('INVALID_RESPONSE');
  return value as unknown as FuzDropImportResponse;
}
export function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Polling cancelled.', 'AbortError')); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException('Polling cancelled.', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, milliseconds);
    signal.addEventListener('abort', abort, { once: true });
  });
}
export interface PollOptions {
  jobId: string; signal: AbortSignal; onJob: (job: AnalysisJob) => void;
  initialJob?: AnalysisJob; immediate?: boolean; intervalMs?: number;
  fetchJob?: typeof getAnalysis; wait?: typeof abortableDelay;
}
/** Sequential GETs only. A failed poll rejects; retries never resubmit the analysis. */
export async function pollAnalysis(options: PollOptions): Promise<AnalysisJob> {
  const { signal, onJob, jobId, initialJob, fetchJob = getAnalysis, wait = abortableDelay } = options;
  const interval = options.intervalMs ?? 1000;
  if (initialJob && isTerminalJob(initialJob)) return initialJob;
  let immediate = options.immediate ?? false;
  for (;;) {
    if (!immediate) await wait(interval, signal);
    immediate = false;
    signal.throwIfAborted();
    const job = await fetchJob(jobId, signal);
    signal.throwIfAborted();
    if (job.job_id !== jobId) throw new ApiError('INVALID_RESPONSE');
    onJob(job);
    if (isTerminalJob(job)) return job;
  }
}
