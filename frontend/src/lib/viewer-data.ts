/** Presentation-only mapping. Never calculate scores, regions, or coordinate conversions. */
import type {
  AnalysisJob, ExecutionStatus, FuzDropImportResponse, FuzDropResult, InputSnapshot,
  LRECAResult, SEGResult, SemanticType,
} from './contracts.ts';

export interface NativeResults {
  lreca: LRECAResult | null;
  fuzdrop: FuzDropResult | null;
  seg: SEGResult | null;
}

export function nativeResults(job: AnalysisJob | null): NativeResults {
  const successful = (method: 'lreca' | 'fuzdrop' | 'seg') => {
    const execution = job?.methods[method];
    return execution?.status === 'success' && execution.result?.method === method
      ? execution.result : null;
  };
  const lreca = successful('lreca');
  const fuzdrop = successful('fuzdrop');
  const seg = successful('seg');
  return {
    lreca: lreca?.method === 'lreca' ? lreca : null,
    fuzdrop: fuzdrop?.method === 'fuzdrop' ? fuzdrop : null,
    seg: seg?.method === 'seg' ? seg : null,
  };
}

/** An import preview never replaces any result belonging to an existing job. */
export function displayedFuzDrop(
  job: AnalysisJob | null, imported: FuzDropImportResponse | null,
): FuzDropResult | null {
  return job ? nativeResults(job).fuzdrop : imported;
}

export interface ViewerTrack {
  id: string;
  method: 'lreca' | 'fuzdrop' | 'seg';
  label: string;
  semanticType: SemanticType;
  kind: 'residue' | 'density' | 'region';
  count: number | null;
  available: boolean;
}

export interface ViewerData {
  sequence: string | null;
  sequenceLength: number | null;
  coordinateSystem: 'one_based_inclusive';
  lrecaAttribution: LRECAResult['residue_attribution'];
  lrecaKDE: LRECAResult['kde'];
  lrecaCriticalRegions: LRECAResult['critical_regions'];
  fuzdropResiduePropensity: FuzDropResult['residue_propensity'];
  fuzdropRegions: FuzDropResult['regions'];
  segRegions: SEGResult['regions'] | null;
  tracks: ViewerTrack[];
}

export interface ViewerRegionSelection {
  method: 'lreca' | 'fuzdrop' | 'seg';
  id?: string;
  type?: string;
  start: number;
  end: number;
  semanticType: 'derived_hotspot' | 'region_prediction' | 'region_annotation';
}

export interface ViewerFocusRequest { start: number; end: number; requestId: number }

export function buildViewerData(
  job: AnalysisJob | null, submittedInput: InputSnapshot | null,
): ViewerData {
  const native = nativeResults(job);
  // submittedInput is the immutable snapshot paired with this job by the workspace/history.
  // Prefer a result's canonical sequence; never read the currently edited input or import.
  const snapshotSequence = job && submittedInput?.length === job.sequence.length
    && submittedInput.canonical.length === job.sequence.length ? submittedInput.canonical : null;
  const attribution = native.lreca?.residue_attribution ?? null;
  const kde = native.lreca?.kde ?? null;
  const critical = native.lreca?.critical_regions ?? null;
  const propensity = native.fuzdrop?.residue_propensity ?? null;
  const fuzdropRegions = native.fuzdrop?.regions ?? null;
  const segRegions = native.seg?.regions ?? null;
  const track = (
    id: string, method: ViewerTrack['method'], label: string,
    semanticType: SemanticType, kind: ViewerTrack['kind'], count: number | null,
  ): ViewerTrack => ({ id, method, label, semanticType, kind, count, available: count !== null });
  return {
    sequence: native.lreca?.sequence ?? native.fuzdrop?.sequence ?? snapshotSequence,
    sequenceLength: job?.sequence.length ?? null,
    coordinateSystem: 'one_based_inclusive',
    lrecaAttribution: attribution,
    lrecaKDE: kde,
    lrecaCriticalRegions: critical,
    fuzdropResiduePropensity: propensity,
    fuzdropRegions,
    segRegions,
    tracks: [
      track('lreca-attribution', 'lreca', 'LRECA residue attribution', 'model_attribution',
        'residue', attribution?.length ?? null),
      track('lreca-kde', 'lreca', 'LRECA KDE density', 'derived_hotspot',
        'density', kde?.status === 'success' ? kde.values?.length ?? null : null),
      track('lreca-critical', 'lreca', 'LRECA critical regions', 'derived_hotspot',
        'region', critical?.length ?? null),
      track('fuzdrop-propensity', 'fuzdrop', 'FuzDrop pDP', 'residue_propensity',
        'residue', propensity?.length ?? null),
      track('fuzdrop-regions', 'fuzdrop', 'FuzDrop predicted regions', 'region_prediction',
        'region', fuzdropRegions?.length ?? null),
      track('seg-regions', 'seg', 'SEG low-complexity regions', 'region_annotation',
        'region', segRegions?.length ?? null),
    ],
  };
}

export function formatNumber(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

export function formatCoverage(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—';
}

/** Limit rendered table rows without filtering or reordering the native result. */
export function paginateRows<T>(rows: readonly T[], requestedPage = 0, pageSize = 20) {
  const size = Number.isFinite(pageSize) && pageSize >= 1 ? Math.floor(pageSize) : 20;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const page = Math.min(pages - 1, Math.max(0, Number.isFinite(requestedPage) ? Math.floor(requestedPage) : 0));
  const offset = page * size;
  return { rows: rows.slice(offset, offset + size), page, pages, total: rows.length,
    first: rows.length ? offset + 1 : 0, last: Math.min(offset + size, rows.length) };
}

export function statusPresentation(status: ExecutionStatus | AnalysisJob['status'] | undefined) {
  const labels = {
    queued: ['Queued', 'neutral'], running: ['Running', 'lreca'],
    success: ['Completed', 'success'], partial_success: ['Completed with warnings', 'neutral'],
    failed: ['Failed', 'error'], interrupted: ['Interrupted', 'error'], unavailable: ['Unavailable', 'neutral'],
    external_result_required: ['External result required', 'fuzdrop'], skipped: ['Skipped', 'neutral'],
  } as const;
  const [label, tone] = status ? labels[status] : ['Not selected', 'neutral'];
  return { label, tone };
}

export function explainReason(reason: string | null | undefined): string {
  const messages: Record<string, string> = {
    fuzdrop_external_result_required: 'Import a matching FuzDrop result to calculate the combined score.',
    imported_result_required: 'A matching imported result is required.',
    fuzdrop_global_score_missing: 'The FuzDrop import does not include a global pLLPS score.',
    fuzdrop_result_unavailable: 'The FuzDrop result is unavailable.',
    lreca_result_unavailable: 'A successful LRECA result is required.',
    manual_import_disabled: 'Manual import is disabled by server configuration.',
    integration_contract_unverified: 'DisMeta integration is currently unavailable.',
    automatic_analysis_unavailable: 'Automatic analysis is currently unavailable.',
    METHOD_TIMEOUT: 'The method exceeded its time limit.',
    METHOD_BUSY_AFTER_TIMEOUT: 'The method is finishing cleanup from an earlier request.',
    METHOD_EXECUTION_FAILED: 'The method could not complete this analysis.',
    METHOD_RESULT_INVALID: 'The method returned a result that could not be validated.',
    METHOD_RESULT_SEQUENCE_MISMATCH: 'The method result did not match the submitted sequence.',
    METHOD_EXECUTION_CANCELLED: 'The method execution was cancelled.',
  };
  return reason ? messages[reason] ?? 'This result is currently unavailable.' : 'This result is currently unavailable.';
}
