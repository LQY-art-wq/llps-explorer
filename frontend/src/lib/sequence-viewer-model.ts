/** Pure sequence-presentation model over the validated Module 7 feature model. */
import type {
  FeatureOutputId, FeatureOutputState, FeatureOutputStatus, FeatureRegion, FeatureTooltip,
  FeatureTooltipRow, FeatureTrack, FeatureTrackId, FeatureViewerIssue, FeatureViewerModel,
} from './feature-viewer-model.ts';
import type { MethodId, SemanticType } from './contracts.ts';
import { extractRegionSequence as sliceRegionSequence, residueLabel as formatResidueLabel } from './sequence-viewer-layout.ts';
import type { ViewerRegionSelection } from './viewer-data.ts';

export type ColorMode = 'none' | 'lreca-attribution' | 'lreca-critical'
  | 'fuzdrop-propensity' | 'fuzdrop-regions' | 'seg-regions' | 'dismeta-regions';
export type SequenceMissingStatus = Exclude<FeatureOutputStatus, 'success' | 'empty'>;
export type SequenceValueStatus = 'value' | SequenceMissingStatus;
export type LRECACriticalMembership = 'primary' | 'candidate' | 'no' | SequenceMissingStatus;
export type SequenceRegionMembership = 'yes' | 'no' | SequenceMissingStatus;

export interface SequenceResidue {
  position: number;
  aa: string;
  lrecaAttribution: number | null;
  lrecaAttributionStatus: SequenceValueStatus;
  kdeDensity: number | null;
  kdeDensityStatus: SequenceValueStatus;
  lrecaCriticalMembership: LRECACriticalMembership;
  lrecaCriticalRegions: readonly FeatureRegion[];
  fuzdropPropensity: number | null;
  fuzdropPropensityStatus: SequenceValueStatus;
  fuzdropRegionMembership: SequenceRegionMembership;
  fuzdropRegions: readonly FeatureRegion[];
  segMembership: SequenceRegionMembership;
  segRegions: readonly FeatureRegion[];
  dismetaStatus: 'unavailable';
  /** Preprocessed once so hover never searches all native regions. */
  tooltip: FeatureTooltip;
}

export interface SequenceColorOption {
  id: ColorMode;
  label: string;
  available: boolean;
  status: FeatureOutputStatus;
  help: string;
  unavailableReason: string | null;
}

export interface SequenceViewerModel {
  analysisId: string | null;
  sequence: string | null;
  length: number;
  coordinateSystem: 'one_based_inclusive';
  residues: SequenceResidue[];
  /** Copies of validated native regions in Module 7 track order. */
  regions: FeatureRegion[];
  colorModes: SequenceColorOption[];
  defaultColorMode: ColorMode;
  outputStates: FeatureOutputState[];
  issues: FeatureViewerIssue[];
}

interface OutputDefinition {
  id: FeatureOutputId;
  method: MethodId;
  label: string;
  kind: 'continuous' | 'region';
  semanticType: SemanticType;
  help: string;
}

const OUTPUTS: readonly OutputDefinition[] = [
  { id: 'lreca-attribution', method: 'lreca', label: 'LRECA Attribution', kind: 'continuous',
    semanticType: 'model_attribution', help: 'Grad-CAM model attribution; native 0–1 values.' },
  { id: 'lreca-kde', method: 'lreca', label: 'LRECA KDE', kind: 'continuous',
    semanticType: 'derived_hotspot', help: 'Backend contribution density; not a probability.' },
  { id: 'lreca-critical', method: 'lreca', label: 'LRECA Critical Regions', kind: 'region',
    semanticType: 'derived_hotspot', help: 'Backend primary and candidate hotspots.' },
  { id: 'fuzdrop-propensity', method: 'fuzdrop', label: 'FuzDrop Propensity', kind: 'continuous',
    semanticType: 'residue_propensity', help: 'Imported per-residue pDP; not attribution.' },
  { id: 'fuzdrop-regions', method: 'fuzdrop', label: 'FuzDrop Regions', kind: 'region',
    semanticType: 'region_prediction', help: 'Regions supplied by the validated import.' },
  { id: 'seg-regions', method: 'seg', label: 'Low-complexity Regions — SEG', kind: 'region',
    semanticType: 'region_annotation', help: 'Native SEG low-complexity annotation.' },
  { id: 'dismeta-regions', method: 'dismeta', label: 'IDR — DisMeta', kind: 'region',
    semanticType: 'region_annotation', help: 'DisMeta integration is currently unavailable.' },
];
const COLOR_IDS: readonly ColorMode[] = ['none', 'lreca-attribution', 'lreca-critical',
  'fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions', 'dismeta-regions'];
const DEFAULT_PRIORITY: readonly Exclude<ColorMode, 'none' | 'dismeta-regions'>[] = [
  'lreca-attribution', 'fuzdrop-propensity', 'lreca-critical', 'fuzdrop-regions', 'seg-regions',
];
const STATUS_TEXT: Record<FeatureOutputStatus, string> = {
  success: 'Available', empty: 'No regions', not_provided: 'N/A', not_imported: 'Not imported',
  unavailable: 'Unavailable', pending: 'Pending', failed: 'Failed', not_selected: 'Not selected',
  invalid: 'Invalid output',
};
const KNOWN_STATUS = new Set<FeatureOutputStatus>(Object.keys(STATUS_TEXT) as FeatureOutputStatus[]);

function definition(id: FeatureOutputId): OutputDefinition {
  return OUTPUTS.find((item) => item.id === id)!;
}
function validSequence(model: FeatureViewerModel): model is FeatureViewerModel & { sequence: string } {
  return typeof model.sequence === 'string' && Number.isSafeInteger(model.length) && model.length > 0
    && model.sequence.length === model.length && /^[ACDEFGHIKLMNPQRSTVWY]+$/.test(model.sequence);
}
function cloneRegion(region: FeatureRegion): FeatureRegion {
  const copy: FeatureRegion = { id: region.id, method: region.method, type: region.type, label: region.label,
    start: region.start, end: region.end, length: region.length, semanticType: region.semanticType };
  if (typeof region.score === 'number') copy.score = region.score;
  if (typeof region.isPrimary === 'boolean') copy.isPrimary = region.isPrimary;
  return copy;
}
function safeState(model: FeatureViewerModel, output: OutputDefinition): FeatureOutputState {
  if (output.id === 'dismeta-regions') return { id: output.id, method: output.method, label: output.label,
    kind: output.kind, semanticType: output.semanticType, status: 'unavailable', message: 'DisMeta integration is currently unavailable.' };
  const source = model.outputStates.find((item) => item.id === output.id);
  if (source && source.method === output.method && source.kind === output.kind
    && source.semanticType === output.semanticType && KNOWN_STATUS.has(source.status)) return { ...source };
  return { id: output.id, method: output.method, label: output.label, kind: output.kind,
    semanticType: output.semanticType, status: 'invalid', message: 'Invalid output state.' };
}
function invalidate(states: FeatureOutputState[], issues: FeatureViewerIssue[], id: FeatureOutputId, message: string) {
  const state = states.find((item) => item.id === id)!;
  state.status = 'invalid'; state.message = message;
  issues.push({ outputId: id, code: 'INVALID_TRACK', message });
}
function expectedMethod(id: FeatureTrackId): MethodId {
  return definition(id).method;
}
function validTrackBase(track: FeatureTrack, id: FeatureTrackId): boolean {
  const output = definition(id);
  return track.id === id && track.method === expectedMethod(id) && track.semanticType === output.semanticType;
}
function continuousValues(model: FeatureViewerModel, id: 'lreca-attribution' | 'lreca-kde' | 'fuzdrop-propensity',
  states: FeatureOutputState[], issues: FeatureViewerIssue[]): (number | null)[] | null {
  const state = states.find((item) => item.id === id)!;
  if (state.status !== 'success') return null;
  const candidates = model.tracks.filter((track) => track.id === id);
  if (candidates.length === 0) {
    invalidate(states, issues, id, `Missing ${definition(id).label} sequence track.`);
    return null;
  }
  const track = candidates[0];
  const allowNull = id === 'fuzdrop-propensity';
  const validValue = (value: number | null) => value === null ? allowNull
    : typeof value === 'number' && Number.isFinite(value) && (id === 'lreca-kde' || (value >= 0 && value <= 1));
  if (candidates.length !== 1 || track.kind !== 'continuous' || !validTrackBase(track, id)
    || !Array.isArray(track.values) || track.values.length !== model.length || !track.values.every(validValue)) {
    invalidate(states, issues, id, `Invalid ${definition(id).label} sequence track.`); return null;
  }
  if (track.values.every((value) => value === null)) {
    state.status = 'not_provided'; state.message = 'The imported result contains no pDP values.'; return null;
  }
  return [...track.values];
}
function validRegion(region: FeatureRegion, id: 'lreca-critical' | 'fuzdrop-regions' | 'seg-regions', length: number): boolean {
  if (region === null || typeof region !== 'object' || typeof region.id !== 'string' || !region.id || region.method !== expectedMethod(id)
    || !Number.isSafeInteger(region.start) || !Number.isSafeInteger(region.end)
    || region.start < 1 || region.end < region.start || region.end > length
    || region.length !== region.end - region.start + 1 || region.semanticType !== definition(id).semanticType) return false;
  if (id === 'lreca-critical') return region.type === 'critical_region'
    && typeof region.score === 'number' && Number.isFinite(region.score) && typeof region.isPrimary === 'boolean';
  if (id === 'fuzdrop-regions') return region.type === 'droplet_promoting_region' || region.type === 'aggregation_hotspot';
  return region.type === 'low_complexity_region';
}
function regionValues(model: FeatureViewerModel, id: 'lreca-critical' | 'fuzdrop-regions' | 'seg-regions',
  states: FeatureOutputState[], issues: FeatureViewerIssue[]): FeatureRegion[] | null {
  const state = states.find((item) => item.id === id)!;
  if (state.status !== 'success' && state.status !== 'empty') return null;
  const candidates = model.tracks.filter((track) => track.id === id);
  if (candidates.length === 0) {
    invalidate(states, issues, id, `Missing ${definition(id).label} sequence regions.`);
    return null;
  }
  const track = candidates[0];
  if (candidates.length !== 1 || track.kind !== 'region' || !validTrackBase(track, id)
    || !Array.isArray(track.regions)
    || !track.regions.every((region) => validRegion(region, id, model.length))
    || (id === 'lreca-critical' && track.regions.length > 0
      && track.regions.filter((region) => region.isPrimary).length !== 1)) {
    invalidate(states, issues, id, `Invalid ${definition(id).label} sequence regions.`); return null;
  }
  return track.regions.map(cloneRegion);
}
function missingStatus(state: FeatureOutputState): SequenceMissingStatus {
  return state.status === 'success' || state.status === 'empty' ? 'invalid' : state.status;
}
function valueStatus(value: number | null, state: FeatureOutputState): SequenceValueStatus {
  return value === null ? (state.status === 'success' ? 'not_provided' : missingStatus(state)) : 'value';
}
function tooltipRow(output: OutputDefinition, state: FeatureOutputState, value: number | null,
  regions: readonly FeatureRegion[] | null): FeatureTooltipRow {
  const base = { id: output.id, method: output.method, label: state.label, value: null, regions: [] as FeatureRegion[] };
  if (output.kind === 'continuous' && value !== null) return { ...base, status: 'value', value, text: null };
  if (output.kind === 'region' && regions !== null) return regions.length
    ? { ...base, status: 'yes', text: 'Yes', regions: regions.map(cloneRegion) }
    : { ...base, status: 'no', text: 'No' };
  const status = state.status === 'success' ? 'not_provided' : state.status === 'empty' ? 'no' : state.status;
  return { ...base, status, text: status === 'no' ? 'No' : STATUS_TEXT[status] };
}

export function buildSequenceViewerModel(feature: FeatureViewerModel): SequenceViewerModel {
  const states = OUTPUTS.map((output) => safeState(feature, output));
  const issues = feature.issues.map((issue) => ({ ...issue }));
  const base = { analysisId: typeof feature.analysisId === 'string' ? feature.analysisId : null,
    coordinateSystem: 'one_based_inclusive' as const, outputStates: states, issues };
  if (!validSequence(feature)) {
    if (feature.sequence !== null || feature.length !== 0) issues.push({ outputId: 'sequence', code: 'INVALID_SEQUENCE',
      message: 'Invalid normalized sequence for the sequence viewer.' });
    const colorModes = buildColorOptions(states, new Set());
    return { ...base, sequence: null, length: 0, residues: [], regions: [], colorModes, defaultColorMode: 'none' };
  }

  const attribution = continuousValues(feature, 'lreca-attribution', states, issues);
  const kde = continuousValues(feature, 'lreca-kde', states, issues);
  const propensity = continuousValues(feature, 'fuzdrop-propensity', states, issues);
  const critical = regionValues(feature, 'lreca-critical', states, issues);
  const fuzdrop = regionValues(feature, 'fuzdrop-regions', states, issues);
  const seg = regionValues(feature, 'seg-regions', states, issues);
  const memberships = {
    critical: Array.from({ length: feature.length }, (): FeatureRegion[] => []),
    fuzdrop: Array.from({ length: feature.length }, (): FeatureRegion[] => []),
    seg: Array.from({ length: feature.length }, (): FeatureRegion[] => []),
  };
  for (const [regions, target] of [[critical, memberships.critical], [fuzdrop, memberships.fuzdrop],
    [seg, memberships.seg]] as const) {
    for (const region of regions ?? []) {
      for (let position = region.start; position <= region.end; position++) target[position - 1].push(region);
    }
  }
  const state = (id: FeatureOutputId) => states.find((item) => item.id === id)!;
  const residues = Array.from(feature.sequence, (aa, index): SequenceResidue => {
    const position = index + 1;
    const criticalHere = memberships.critical[index];
    const fuzdropHere = memberships.fuzdrop[index];
    const segHere = memberships.seg[index];
    const criticalMembership: LRECACriticalMembership = critical === null ? missingStatus(state('lreca-critical'))
      : criticalHere.some((region) => region.isPrimary) ? 'primary' : criticalHere.length ? 'candidate' : 'no';
    const binary = (regions: FeatureRegion[] | null, inside: readonly FeatureRegion[], id: FeatureOutputId): SequenceRegionMembership =>
      regions === null ? missingStatus(state(id)) : inside.length ? 'yes' : 'no';
    const attrValue = attribution?.[index] ?? null;
    const kdeValue = kde?.[index] ?? null;
    const pdpValue = propensity?.[index] ?? null;
    const rows = OUTPUTS.map((output) => {
      if (output.id === 'lreca-attribution') return tooltipRow(output, state(output.id), attrValue, null);
      if (output.id === 'lreca-kde') return tooltipRow(output, state(output.id), kdeValue, null);
      if (output.id === 'fuzdrop-propensity') return tooltipRow(output, state(output.id), pdpValue, null);
      if (output.id === 'lreca-critical') return tooltipRow(output, state(output.id), null, critical === null ? null : criticalHere);
      if (output.id === 'fuzdrop-regions') return tooltipRow(output, state(output.id), null, fuzdrop === null ? null : fuzdropHere);
      if (output.id === 'seg-regions') return tooltipRow(output, state(output.id), null, seg === null ? null : segHere);
      return tooltipRow(output, state(output.id), null, null);
    });
    return { position, aa, lrecaAttribution: attrValue, lrecaAttributionStatus: valueStatus(attrValue, state('lreca-attribution')),
      kdeDensity: kdeValue, kdeDensityStatus: valueStatus(kdeValue, state('lreca-kde')),
      lrecaCriticalMembership: criticalMembership, lrecaCriticalRegions: criticalHere.map(cloneRegion),
      fuzdropPropensity: pdpValue, fuzdropPropensityStatus: valueStatus(pdpValue, state('fuzdrop-propensity')),
      fuzdropRegionMembership: binary(fuzdrop, fuzdropHere, 'fuzdrop-regions'), fuzdropRegions: fuzdropHere.map(cloneRegion),
      segMembership: binary(seg, segHere, 'seg-regions'), segRegions: segHere.map(cloneRegion), dismetaStatus: 'unavailable',
      tooltip: { position, aa, rows } };
  });
  const regions = [...(critical ?? []), ...(fuzdrop ?? []), ...(seg ?? [])].map(cloneRegion);
  const available = new Set<ColorMode>();
  if (attribution !== null) available.add('lreca-attribution');
  if (propensity !== null) available.add('fuzdrop-propensity');
  if (critical?.length) available.add('lreca-critical');
  if (fuzdrop?.length) available.add('fuzdrop-regions');
  if (seg?.length) available.add('seg-regions');
  const colorModes = buildColorOptions(states, available);
  const defaultColorMode = DEFAULT_PRIORITY.find((id) => available.has(id)) ?? 'none';
  return { ...base, sequence: feature.sequence, length: feature.length, residues, regions, colorModes, defaultColorMode };
}

function buildColorOptions(states: FeatureOutputState[], available: ReadonlySet<ColorMode>): SequenceColorOption[] {
  return COLOR_IDS.map((id) => {
    if (id === 'none') return { id, label: 'None', available: true, status: 'success', help: 'Show amino-acid letters without scientific coloring.', unavailableReason: null };
    const output = definition(id);
    const state = states.find((item) => item.id === id)!;
    const enabled = id !== 'dismeta-regions' && available.has(id) && state.status !== 'invalid';
    return { id, label: output.label, available: enabled, status: state.status, help: output.help,
      unavailableReason: enabled ? null : state.message || STATUS_TEXT[state.status] };
  });
}

/** A display-only mapping. It never normalizes across a protein. */
export function displayIntensity(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : null;
}

export function getSequenceTooltip(model: SequenceViewerModel, position: number): FeatureTooltip | null {
  return Number.isSafeInteger(position) && position >= 1 && position <= model.length ? model.residues[position - 1].tooltip : null;
}

/** Rejects stale/arbitrary selections before applying the shared inclusive slicing helper. */
export function extractSelectedRegionSequence(model: SequenceViewerModel, selected: ViewerRegionSelection | null): string | null {
  if (!model.sequence || !selected) return null;
  const region = model.regions.find((item) => item.method === selected.method
    && item.start === selected.start && item.end === selected.end
    && (!selected.type || selected.type === item.type) && (!selected.id || selected.id === item.id));
  return region ? sliceRegionSequence(model.sequence, region.start, region.end) : null;
}

export function residueCopyLabel(model: SequenceViewerModel, position: number): string | null {
  return model.sequence && Number.isSafeInteger(position) && position >= 1 && position <= model.length
    ? formatResidueLabel(model.sequence, position) : null;
}
