import type { AnalysisJob, AnalysisRequest, AutomaticMethodId, FuzDropImportResponse, InputSnapshot, MethodDescriptor, MethodId, PredictionMode, Weights } from './contracts.ts';
import { parseSequence, sequenceNameError, sequenceSha256, trimPythonWhitespace } from './sequence.ts';

export type ImportState = 'not_imported' | 'validating' | 'valid' | 'invalid' | 'sequence_mismatch' | 'expired';
export interface DraftSelection {
  rawSequence: string; sequenceName: string; methods: MethodDescriptor[];
  selectedAutomatic: AutomaticMethodId[]; imported: FuzDropImportResponse | null;
  useFuzDrop: boolean; mode: PredictionMode; lrecaPercent: number;
}
export function availableAutomaticMethods(methods: MethodDescriptor[]): AutomaticMethodId[] {
  return (['lreca', 'seg'] as const).filter((id) => methods.some((method) => method.id === id
    && method.method_supported && method.available && method.automatic_analysis_available
    && method.integration_mode === 'local_automatic'));
}
export function complementaryWeights(lrecaPercent: number): Weights | null {
  if (!Number.isFinite(lrecaPercent) || lrecaPercent < 0 || lrecaPercent > 100) return null;
  return { lreca: lrecaPercent / 100, fuzdrop: (100 - lrecaPercent) / 100 };
}
export function importedStateForSequence(result: FuzDropImportResponse | null, canonical: string, now = Date.now()): ImportState {
  if (!result) return 'not_imported';
  if (result.validation_status !== 'valid' || !result.result_id || result.method !== 'fuzdrop'
    || result.status !== 'success' || !/^[a-f0-9]{64}$/.test(result.sequence_sha256)) return 'invalid';
  if (result.sequence !== canonical || result.sequence_length !== [...canonical].length) return 'sequence_mismatch';
  const expiry = Date.parse(result.expires_at);
  if (!Number.isFinite(expiry)) return 'invalid';
  return expiry <= now ? 'expired' : 'valid';
}
export async function validateImportedResponse(result: FuzDropImportResponse, canonical: string, now = Date.now()): Promise<ImportState> {
  const state = importedStateForSequence(result, canonical, now);
  if (state !== 'valid') return state;
  return await sequenceSha256(canonical) === result.sequence_sha256 ? 'valid' : 'sequence_mismatch';
}
export const IMPORT_MESSAGES: Record<ImportState, string | null> = {
  not_imported: null, validating: null, valid: null,
  invalid: 'The imported result could not be validated. Import it again.',
  sequence_mismatch: 'Imported result no longer matches this sequence. Import it again.',
  expired: 'The imported result has expired. Import it again.',
};
/** In-memory binding with monotonic revisions: changing away and back cannot revive an import. */
export class ImportSession {
  revision = 0;
  private request = 0;
  imported: FuzDropImportResponse | null = null;
  status: ImportState = 'not_imported';
  invalidate(): void {
    this.revision += 1; this.request += 1;
    if (this.imported || this.status === 'validating') this.status = 'sequence_mismatch';
    this.imported = null;
  }
  remove(): void {
    this.request += 1; this.imported = null; this.status = 'not_imported';
  }
  expire(now = Date.now()): boolean {
    if (this.imported && Date.parse(this.imported.expires_at) <= now) {
      this.request += 1; this.imported = null; this.status = 'expired'; return true;
    }
    return false;
  }
  async accept(result: FuzDropImportResponse, canonical: string, revision: number): Promise<boolean> {
    if (revision !== this.revision) return false;
    const request = ++this.request;
    this.status = 'validating';
    let status: ImportState;
    try { status = await validateImportedResponse(result, canonical); }
    catch { status = 'invalid'; }
    if (revision !== this.revision || request !== this.request) return false;
    // The hash computation may cross an expiry boundary.
    if (status === 'valid') status = importedStateForSequence(result, canonical);
    this.status = status;
    this.imported = status === 'valid' ? result : null;
    return status === 'valid';
  }
}
export function evaluateDraft(draft: DraftSelection, now = Date.now()) {
  const validation = parseSequence(draft.rawSequence);
  const available = availableAutomaticMethods(draft.methods);
  const selected: MethodId[] = available.filter((id) => draft.selectedAutomatic.includes(id));
  const importState = importedStateForSequence(draft.imported, validation.canonical, now);
  const manualAvailable = draft.methods.some((method) => method.id === 'fuzdrop' && method.manual_import_available);
  const usableImport = validation.valid && importState === 'valid' && manualAvailable;
  if (usableImport && draft.useFuzDrop) selected.push('fuzdrop');
  let weightedDisabledReason: string | null = null;
  if (!selected.includes('lreca')) weightedDisabledReason = 'Select an available LRECA model to use weighted mode.';
  else if (!usableImport) weightedDisabledReason = 'Import a valid FuzDrop result for this sequence to enable weighted mode.';
  else if (!draft.useFuzDrop) weightedDisabledReason = 'Enable “Use FuzDrop in this analysis” to use weighted mode.';
  else if (typeof draft.imported?.raw_score !== 'number' || !Number.isFinite(draft.imported.raw_score)
    || typeof draft.imported.calibrated_score !== 'number' || !Number.isFinite(draft.imported.calibrated_score)) weightedDisabledReason = 'The FuzDrop import needs a global pLLPS score for weighted mode.';
  const weights = complementaryWeights(draft.lrecaPercent);
  let runDisabledReason = validation.error?.message ?? sequenceNameError(draft.sequenceName);
  if (!runDisabledReason && !selected.length) runDisabledReason = 'Select at least one available method or enable a valid FuzDrop import.';
  if (!runDisabledReason && draft.mode === 'weighted') runDisabledReason = weightedDisabledReason ?? (weights ? null : 'Weights must be numbers between 0 and 100%.');
  const request: AnalysisRequest | null = runDisabledReason ? null : {
    sequence: validation.canonical,
    sequence_name: trimPythonWhitespace(draft.sequenceName) || null,
    selected_methods: selected,
    prediction_mode: draft.mode,
    weights: draft.mode === 'weighted' ? weights : null,
    external_results: selected.includes('fuzdrop') && draft.imported ? { fuzdrop: { result_id: draft.imported.result_id } } : {},
  };
  return { validation, importState, selectedMethods: selected, weightedDisabledReason, runDisabledReason, request };
}
export function isTerminalJob(job: Pick<AnalysisJob, 'status'>): boolean {
  return job.status !== 'queued' && job.status !== 'running';
}
export function snapshotInput(draft: Pick<DraftSelection, 'rawSequence' | 'sequenceName'>, submittedAt = new Date().toISOString()): InputSnapshot {
  const parsed = parseSequence(draft.rawSequence);
  return { rawSequence: draft.rawSequence, canonical: parsed.canonical, sequenceName: trimPythonWhitespace(draft.sequenceName) || null,
    length: parsed.length, validResidues: parsed.validResidues, inputType: parsed.inputType, submittedAt };
}
