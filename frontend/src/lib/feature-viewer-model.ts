/** Pure rendering model over the existing native-result mapping. No scientific computation. */
import type { AnalysisJob, InputSnapshot, MethodId, SemanticType } from './contracts.ts';
import { buildViewerData, nativeResults } from './viewer-data.ts';
import type { ViewerRegionSelection } from './viewer-data.ts';

export type FeatureTrackId = 'lreca-attribution' | 'lreca-kde' | 'lreca-critical'
  | 'fuzdrop-propensity' | 'fuzdrop-regions' | 'seg-regions';
export type FeatureOutputId = FeatureTrackId | 'dismeta-regions';
export type FeatureOutputStatus = 'success' | 'empty' | 'not_provided' | 'not_imported'
  | 'unavailable' | 'pending' | 'failed' | 'not_selected' | 'invalid';
export interface FeatureRegion extends ViewerRegionSelection {
  id: string;
  type: 'critical_region' | 'droplet_promoting_region' | 'aggregation_hotspot' | 'low_complexity_region';
  label: string;
  length: number;
  score?: number;
  isPrimary?: boolean;
}
interface FeatureTrackBase {
  id: FeatureTrackId;
  method: 'lreca' | 'fuzdrop' | 'seg';
  label: string;
  semanticType: SemanticType;
  description: string;
}
export interface ContinuousFeatureTrack extends FeatureTrackBase {
  kind: 'continuous';
  values: (number | null)[];
  valueLabel: string;
  /** Known scale only; null requests a visual axis from the unmodified finite values. */
  valueDomain: [number, number] | null;
}
export interface RegionFeatureTrack extends FeatureTrackBase {
  kind: 'region';
  regions: FeatureRegion[];
}
export type FeatureTrack = ContinuousFeatureTrack | RegionFeatureTrack;
export interface FeatureOutputState {
  id: FeatureOutputId;
  method: MethodId;
  label: string;
  kind: 'continuous' | 'region';
  semanticType: SemanticType;
  status: FeatureOutputStatus;
  message: string;
}
export interface FeatureViewerIssue {
  outputId: FeatureOutputId | 'sequence';
  code: 'INVALID_SEQUENCE' | 'INVALID_NATIVE_RESULT' | 'SEQUENCE_MISMATCH' | 'INVALID_TRACK';
  message: string;
}
export interface FeatureViewerModel {
  analysisId: string | null;
  sequence: string | null;
  length: number;
  coordinateSystem: 'one_based_inclusive';
  tracks: FeatureTrack[];
  outputStates: FeatureOutputState[];
  issues: FeatureViewerIssue[];
}
export interface FeatureTooltipRow {
  id: FeatureOutputId;
  method: MethodId;
  label: string;
  status: FeatureOutputStatus | 'value' | 'yes' | 'no';
  value: number | null;
  text: string | null;
  regions: FeatureRegion[];
}
export interface FeatureTooltip {
  position: number;
  aa: string;
  rows: FeatureTooltipRow[];
}

interface OutputDefinition {
  id: FeatureOutputId; method: MethodId; label: string;
  kind: 'continuous' | 'region'; semanticType: SemanticType; description: string;
}
const OUTPUTS: readonly OutputDefinition[] = [
  { id: 'lreca-attribution', method: 'lreca', label: 'LRECA Residue Attribution', kind: 'continuous',
    semanticType: 'model_attribution', description: 'Grad-CAM model attribution; original normalized values.' },
  { id: 'lreca-kde', method: 'lreca', label: 'LRECA KDE Contribution Density', kind: 'continuous',
    semanticType: 'derived_hotspot', description: 'Backend contribution density; not a probability.' },
  { id: 'lreca-critical', method: 'lreca', label: 'LRECA Critical Regions', kind: 'region',
    semanticType: 'derived_hotspot', description: 'Backend candidate and primary hotspots; inclusive coordinates.' },
  { id: 'fuzdrop-propensity', method: 'fuzdrop', label: 'FuzDrop Residue Propensity', kind: 'continuous',
    semanticType: 'residue_propensity', description: 'Imported per-residue pDP; not model attribution.' },
  { id: 'fuzdrop-regions', method: 'fuzdrop', label: 'FuzDrop Predicted Regions', kind: 'region',
    semanticType: 'region_prediction', description: 'Regions supplied in the validated import; user-declared origin.' },
  { id: 'seg-regions', method: 'seg', label: 'Low-complexity Regions — SEG', kind: 'region',
    semanticType: 'region_annotation', description: 'Native SEG low-complexity annotations.' },
  { id: 'dismeta-regions', method: 'dismeta', label: 'IDR — DisMeta', kind: 'region',
    semanticType: 'region_annotation', description: 'DisMeta integration is unavailable.' },
];
const STATE_TEXT: Record<FeatureOutputStatus, string> = {
  success: 'Available', empty: 'No regions', not_provided: 'N/A', not_imported: 'Not imported',
  unavailable: 'Unavailable', pending: 'Pending', failed: 'Failed', not_selected: 'Not selected',
  invalid: 'Invalid output',
};
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function canonical(value: unknown, length: number): value is string {
  return typeof value === 'string' && value.length === length && /^[ACDEFGHIKLMNPQRSTVWY]+$/.test(value);
}
function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
function probability(value: unknown): value is number {
  return finite(value) && value >= 0 && value <= 1;
}
function initialStatus(job: AnalysisJob | null, method: MethodId): FeatureOutputStatus {
  if (method === 'dismeta') return 'unavailable';
  if (!job || !job.selected_methods.includes(method)) return method === 'fuzdrop' ? 'not_imported' : 'not_selected';
  const execution = job.methods[method];
  if (!execution) return 'invalid';
  if (execution.status === 'queued' || execution.status === 'running') return 'pending';
  if (execution.status === 'external_result_required') return method === 'fuzdrop' ? 'not_imported' : 'not_provided';
  if (execution.status === 'failed') return 'failed';
  if (execution.status === 'unavailable') return 'unavailable';
  if (execution.status === 'skipped') return 'not_selected';
  return execution.status === 'success' ? 'success' : 'invalid';
}
function emptyModel(job: AnalysisJob | null): FeatureViewerModel {
  return { analysisId: job?.job_id ?? null, sequence: null, length: 0,
    coordinateSystem: 'one_based_inclusive', tracks: [], issues: [],
    outputStates: OUTPUTS.map(({ description: _description, ...definition }) => {
      void _description;
      const status = initialStatus(job, definition.method);
      return { ...definition, status, message: STATE_TEXT[status] };
    }),
  };
}

function residueValues(raw: unknown, sequence: string, semantic: string, allowNull: boolean): (number | null)[] | null {
  if (!Array.isArray(raw) || raw.length !== sequence.length) return null;
  const values: (number | null)[] = [];
  for (const [index, row] of raw.entries()) {
    if (!record(row) || row.position !== index + 1 || row.aa !== sequence[index]
      || row.semantic_type !== semantic || (semantic === 'residue_propensity' && row.score_name !== 'pDP')) return null;
    if (row.score === null && allowNull) values.push(null);
    else if (probability(row.score)) values.push(row.score);
    else return null;
  }
  return values;
}
function densityValues(raw: unknown, length: number): number[] | null {
  return Array.isArray(raw) && raw.length === length && raw.every(finite) ? [...raw] : null;
}
function regionValues(raw: unknown, definition: OutputDefinition, length: number): FeatureRegion[] | null {
  if (!Array.isArray(raw) || definition.method === 'dismeta') return null;
  const regions: FeatureRegion[] = [];
  for (const [index, row] of raw.entries()) {
    if (!record(row) || !Number.isInteger(row.start) || !Number.isInteger(row.end)
      || typeof row.start !== 'number' || typeof row.end !== 'number'
      || row.start < 1 || row.end < row.start || row.end > length
      || row.length !== row.end - row.start + 1 || row.semantic_type !== definition.semanticType) return null;
    const base = { id: `${definition.id}:${index}:${row.start}-${row.end}`, method: definition.method,
      start: row.start, end: row.end, length: row.length as number,
      semanticType: definition.semanticType as ViewerRegionSelection['semanticType'] };
    if (definition.method === 'lreca') {
      if (!finite(row.score) || typeof row.is_primary !== 'boolean') return null;
      regions.push({ ...base, type: 'critical_region', label: row.is_primary ? 'Primary hotspot' : 'Candidate hotspot',
        score: row.score, isPrimary: row.is_primary });
    } else if (definition.method === 'fuzdrop') {
      if (row.type !== 'droplet_promoting_region' && row.type !== 'aggregation_hotspot') return null;
      const label = row.type === 'droplet_promoting_region' ? 'Droplet-promoting region' : 'Aggregation hot-spot';
      if (row.official_type !== label) return null;
      regions.push({ ...base, type: row.type, label });
    } else regions.push({ ...base, type: 'low_complexity_region', label: 'Low-complexity region' });
  }
  if (definition.method === 'lreca' && regions.length && regions.filter((region) => region.isPrimary).length !== 1) return null;
  return regions;
}

export function buildFeatureViewerModel(job: AnalysisJob | null, input: InputSnapshot | null): FeatureViewerModel {
  // The API validates the envelope; guard it again so malformed optional inputs cannot crash a view.
  if (!job) return emptyModel(null);
  if (!record(job.sequence) || !Number.isSafeInteger(job.sequence.length) || job.sequence.length < 1
    || !record(job.methods) || !Array.isArray(job.selected_methods)) {
    const invalid = emptyModel(null);
    invalid.analysisId = typeof job.job_id === 'string' ? job.job_id : null;
    invalid.issues.push({ outputId: 'sequence', code: 'INVALID_SEQUENCE', message: 'Invalid analysis sequence metadata.' });
    return invalid;
  }
  const model = emptyModel(job);
  model.length = job.sequence.length;
  const validInput = input?.length === model.length && canonical(input.canonical, model.length) ? input : null;
  const data = buildViewerData(job, validInput);
  const native = nativeResults(job);
  // This immutable snapshot is paired with this job by workspace/history, never the live draft.
  const nativeSequences = [
    job.selected_methods.includes('lreca') && native.lreca?.status === 'success' ? native.lreca.sequence : null,
    job.selected_methods.includes('fuzdrop') && native.fuzdrop?.status === 'success'
      && native.fuzdrop.source === 'manual_import_of_official_result' ? native.fuzdrop.sequence : null,
  ];
  model.sequence = validInput?.canonical ?? nativeSequences.find((value) => canonical(value, model.length)) ?? null;
  const setState = (id: FeatureOutputId, status: FeatureOutputStatus, message = STATE_TEXT[status]) => {
    const state = model.outputStates.find((output) => output.id === id)!;
    state.status = status; state.message = message;
  };
  const issue = (id: FeatureOutputId, code: FeatureViewerIssue['code'], message: string) => {
    setState(id, 'invalid', message); model.issues.push({ outputId: id, code, message });
  };
  if (!model.sequence) {
    model.issues.push({ outputId: 'sequence', code: 'INVALID_SEQUENCE', message: 'A matching normalized sequence is required for the feature viewer.' });
    for (const state of model.outputStates) if (state.status === 'success') setState(state.id, 'invalid', 'The normalized sequence is unavailable.');
    return model;
  }
  for (const definition of OUTPUTS) {
    const { id, method, label, semanticType, description } = definition;
    const current = model.outputStates.find((state) => state.id === id)!;
    if (method === 'dismeta' || current.status !== 'success') continue;
    const result = native[method];
    if (!result || result.status !== 'success' || job.methods[method]?.method !== method) {
      issue(id, 'INVALID_NATIVE_RESULT', `Invalid ${label} result.`); continue;
    }
    if (result.sequence_length !== model.length
      || ('sequence' in result && result.sequence !== model.sequence)
      || ('sequence_sha256' in result && result.sequence_sha256 !== job.sequence.sha256)) {
      issue(id, 'SEQUENCE_MISMATCH', `${label} does not match the analysis sequence.`); continue;
    }
    if (method === 'fuzdrop' && (native.fuzdrop?.source !== 'manual_import_of_official_result'
      || native.fuzdrop.coordinate_system !== 'one_based_inclusive')) {
      issue(id, 'INVALID_NATIVE_RESULT', 'FuzDrop tracks require the validated imported result.'); continue;
    }
    const base = { id: id as FeatureTrackId, method, label, semanticType, description };
    if (id === 'lreca-attribution' || id === 'fuzdrop-propensity') {
      const raw = id === 'lreca-attribution' ? data.lrecaAttribution : data.fuzdropResiduePropensity;
      if (raw == null || (id === 'lreca-attribution' && native.lreca?.attribution_status !== 'success')) {
        setState(id, 'not_provided', id === 'fuzdrop-propensity' ? 'FuzDrop residue-level data were not included in the imported result.' : 'Residue attribution was not provided in this result.'); continue;
      }
      const values = residueValues(raw, model.sequence, semanticType, id === 'fuzdrop-propensity');
      if (!values) { issue(id, 'INVALID_TRACK', `Invalid ${label} track.`); continue; }
      if (values.every((value) => value === null)) { setState(id, 'not_provided', 'The imported result contains no pDP values.'); continue; }
      model.tracks.push({ ...base, kind: 'continuous', values, valueDomain: [0, 1],
        valueLabel: id === 'lreca-attribution' ? 'Attribution' : 'pDP' });
    } else if (id === 'lreca-kde') {
      if (data.lrecaKDE == null || data.lrecaKDE.status === 'unavailable') {
        setState(id, 'not_provided', 'KDE values are not available in this result.'); continue;
      }
      const values = densityValues(data.lrecaKDE.values, model.length);
      if (data.lrecaKDE.status !== 'success' || data.lrecaKDE.semantic_type !== 'derived_hotspot' || !values) {
        issue(id, 'INVALID_TRACK', 'Invalid LRECA KDE density track.'); continue;
      }
      model.tracks.push({ ...base, kind: 'continuous', values, valueDomain: null, valueLabel: 'Contribution density' });
    } else {
      const raw = id === 'lreca-critical' ? data.lrecaCriticalRegions : id === 'fuzdrop-regions' ? data.fuzdropRegions : data.segRegions;
      if (raw == null) { setState(id, 'not_provided', `${label} were not provided in this result.`); continue; }
      const regions = regionValues(raw, definition, model.length);
      if (!regions) { issue(id, 'INVALID_TRACK', `Invalid ${label} track.`); continue; }
      setState(id, regions.length ? 'success' : 'empty');
      model.tracks.push({ ...base, kind: 'region', regions });
    }
  }
  return model;
}

export function getFeatureTooltip(model: FeatureViewerModel, position: number): FeatureTooltip | null {
  if (!model.sequence || !Number.isInteger(position) || position < 1 || position > model.length) return null;
  const rows = model.outputStates.map((output): FeatureTooltipRow => {
    const base = { id: output.id, method: output.method, label: output.label, value: null, regions: [] };
    const track = model.tracks.find((item) => item.id === output.id);
    if (track?.kind === 'continuous') {
      const value = track.values[position - 1];
      return value === null ? { ...base, status: 'not_provided', text: 'N/A' }
        : { ...base, status: 'value', value, text: null };
    }
    if (track?.kind === 'region') {
      const regions = track.regions.filter((region) => region.start <= position && position <= region.end);
      return regions.length ? { ...base, status: 'yes', text: 'Yes', regions: regions.map((region) => ({ ...region })) }
        : { ...base, status: 'no', text: 'No' };
    }
    return { ...base, status: output.status, text: STATE_TEXT[output.status] };
  });
  return { position, aa: model.sequence[position - 1], rows };
}
