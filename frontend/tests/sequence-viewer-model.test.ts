/** Sequence presentation tests over saved responses; no scientific inference runs here. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import type { AnalysisJob, InputSnapshot } from '../src/lib/contracts.ts';
import { createFeatureTestFixture, FEATURE_TEST_LENGTHS } from '../src/lib/feature-test-fixtures.ts';
import { buildFeatureViewerModel } from '../src/lib/feature-viewer-model.ts';
import type { ContinuousFeatureTrack, FeatureViewerModel, RegionFeatureTrack } from '../src/lib/feature-viewer-model.ts';
import {
  buildSequenceViewerModel, displayIntensity, extractSelectedRegionSequence, getSequenceTooltip,
  residueCopyLabel,
} from '../src/lib/sequence-viewer-model.ts';
import type { ColorMode, SequenceViewerModel } from '../src/lib/sequence-viewer-model.ts';

const module7 = new URL('../../docs/audit/module7_browser/api/', import.meta.url);
const module6 = new URL('../../docs/audit/module6_browser/api/', import.meta.url);
const jobs = Object.fromEntries(['A', 'B', 'C', 'D', 'E'].map((name) => [name,
  JSON.parse(readFileSync(new URL(`${name}_job.json`, module7), 'utf8')) as AnalysisJob]));
jobs.H = JSON.parse(readFileSync(new URL('H_job.json', module6), 'utf8')) as AnalysisJob;
const canonical = (jobs.A.methods.lreca!.result as { sequence: string }).sequence;
function input(job: AnalysisJob): InputSnapshot {
  return { rawSequence: `>human_positive_line_1\n${canonical}`, canonical, sequenceName: job.sequence.name,
    length: canonical.length, validResidues: canonical.length, inputType: 'fasta', submittedAt: job.created_at };
}
function feature(name: keyof typeof jobs): FeatureViewerModel {
  const job = structuredClone(jobs[name]);
  return buildFeatureViewerModel(job, input(job));
}
function sequence(name: keyof typeof jobs): SequenceViewerModel {
  return buildSequenceViewerModel(feature(name));
}
function option(model: SequenceViewerModel, id: ColorMode) {
  const result = model.colorModes.find((item) => item.id === id); assert.ok(result); return result;
}
function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze); Object.freeze(value);
  }
  return value;
}

test('real A maps the canonical 248 residues, exact LRECA values and backend critical memberships', () => {
  const model = sequence('A');
  assert.equal(model.analysisId, jobs.A.job_id); assert.equal(model.sequence, canonical); assert.equal(model.length, 248);
  assert.equal(model.residues.length, 248); assert.equal(model.residues[0].position, 1); assert.equal(model.residues[247].position, 248);
  assert.equal(model.residues[0].aa, 'M'); assert.equal(model.residues[105].aa, 'G'); assert.equal(model.residues[242].aa, 'R'); assert.equal(model.residues[247].aa, 'T');
  const native = jobs.A.methods.lreca!.result as { residue_attribution: { score: number }[]; kde: { values: number[] } };
  for (const position of [1, 106, 243, 248]) {
    assert.equal(model.residues[position - 1].lrecaAttribution, native.residue_attribution[position - 1].score);
    assert.equal(model.residues[position - 1].kdeDensity, native.kde.values[position - 1]);
  }
  assert.equal(model.residues[1].lrecaCriticalMembership, 'candidate');
  assert.equal(model.residues[105].lrecaCriticalMembership, 'primary');
  assert.equal(model.residues[242].lrecaCriticalMembership, 'candidate');
  assert.equal(model.residues[247].lrecaCriticalMembership, 'no');
  assert.equal(model.defaultColorMode, 'lreca-attribution');
  assert.equal(option(model, 'lreca-attribution').available, true);
  assert.equal(option(model, 'dismeta-regions').available, false);
  assert.equal(option(model, 'dismeta-regions').status, 'unavailable');
});

test('real B SEG-only maps Yes/No without assuming prediction output and defaults to the LCR mode', () => {
  const model = sequence('B');
  assert.equal(model.defaultColorMode, 'seg-regions');
  assert.equal(option(model, 'lreca-attribution').status, 'not_selected');
  assert.equal(option(model, 'lreca-attribution').available, false);
  for (const position of [72, 85, 89, 119, 196, 247]) assert.equal(model.residues[position - 1].segMembership, 'yes');
  for (const position of [1, 71, 86, 120, 195, 248]) assert.equal(model.residues[position - 1].segMembership, 'no');
  assert.equal(model.residues[71].lrecaAttribution, null);
  assert.equal(model.residues[71].lrecaAttributionStatus, 'not_selected');
});

test('a successful empty region output reports No but does not enable a meaningless color mode', () => {
  const base = feature('B');
  const track = base.tracks.find((item): item is RegionFeatureTrack => item.id === 'seg-regions' && item.kind === 'region')!;
  track.regions = [];
  const state = base.outputStates.find((item) => item.id === 'seg-regions')!;
  state.status = 'empty'; state.message = 'No regions';
  const model = buildSequenceViewerModel(base);
  assert.equal(model.residues[0].segMembership, 'no');
  assert.equal(model.residues[247].segMembership, 'no');
  assert.equal(option(model, 'seg-regions').available, false);
  assert.equal(option(model, 'seg-regions').status, 'empty');
  assert.equal(model.defaultColorMode, 'none');
});

test('real C combines LRECA and SEG independently while FuzDrop is Not imported and DisMeta Unavailable', () => {
  const model = sequence('C'); const residue = model.residues[44];
  assert.equal(residue.aa, 'I'); assert.equal(residue.lrecaAttributionStatus, 'value');
  assert.equal(residue.segMembership, 'no'); assert.equal(residue.fuzdropPropensity, null);
  assert.equal(residue.fuzdropPropensityStatus, 'not_imported'); assert.equal(residue.fuzdropRegionMembership, 'not_imported');
  assert.equal(residue.dismetaStatus, 'unavailable');
  assert.equal(model.regions.filter((region) => region.method === 'seg').length, 3);
  assert.equal(model.regions.filter((region) => region.method === 'lreca').length, 5);
});

test('real D uses only the validated synthetic import pDP and native region memberships', () => {
  const model = sequence('D'); const residue = model.residues[44];
  assert.equal(residue.position, 45); assert.equal(residue.aa, 'I'); assert.equal(residue.fuzdropPropensity, 0.1);
  assert.equal(residue.fuzdropPropensityStatus, 'value'); assert.equal(residue.fuzdropRegionMembership, 'yes');
  assert.deepEqual(residue.fuzdropRegions.map(({ start, end, length, type }) => ({ start, end, length, type })), [
    { start: 30, end: 45, length: 16, type: 'droplet_promoting_region' },
    { start: 45, end: 60, length: 16, type: 'droplet_promoting_region' },
  ]);
  assert.equal(option(model, 'fuzdrop-propensity').available, true);
  assert.equal(option(model, 'fuzdrop-regions').available, true);
  assert.equal(model.defaultColorMode, 'lreca-attribution');
});

test('real E global-only FuzDrop disables both residue modes and keeps N/A distinct from No', () => {
  const model = sequence('E'); const residue = model.residues[44];
  assert.equal(option(model, 'fuzdrop-propensity').available, false);
  assert.equal(option(model, 'fuzdrop-regions').available, false);
  assert.equal(option(model, 'fuzdrop-propensity').status, 'not_provided');
  assert.equal(option(model, 'fuzdrop-regions').status, 'not_provided');
  assert.equal(residue.fuzdropPropensityStatus, 'not_provided');
  assert.equal(residue.fuzdropRegionMembership, 'not_provided');
  assert.equal(residue.segMembership, 'no');
  const tooltip = getSequenceTooltip(model, 45)!;
  assert.equal(tooltip.rows.find((row) => row.id === 'fuzdrop-propensity')!.text, 'N/A');
  assert.equal(tooltip.rows.find((row) => row.id === 'fuzdrop-regions')!.text, 'N/A');
  assert.equal(tooltip.rows.find((row) => row.id === 'seg-regions')!.text, 'No');
});

test('real H partial success retains LRECA and marks SEG failed without fabricated membership', () => {
  const model = sequence('H'); const residue = model.residues[242];
  assert.equal(residue.lrecaAttributionStatus, 'value'); assert.equal(residue.kdeDensityStatus, 'value');
  assert.equal(residue.segMembership, 'failed'); assert.deepEqual(residue.segRegions, []);
  assert.equal(option(model, 'seg-regions').available, false); assert.equal(option(model, 'seg-regions').status, 'failed');
  assert.equal(option(model, 'lreca-attribution').available, true); assert.equal(model.defaultColorMode, 'lreca-attribution');
});

test('precomputed tooltips retain actual values and never search or replace the canonical residue letter', () => {
  const model = sequence('D');
  for (const position of [1, 45, 106, 243, 248]) {
    const tooltip = getSequenceTooltip(model, position)!;
    assert.equal(tooltip, model.residues[position - 1].tooltip);
    assert.equal(tooltip.position, position); assert.equal(tooltip.aa, canonical[position - 1]);
  }
  for (const position of [0, -1, 249, 1.5, NaN, Infinity]) assert.equal(getSequenceTooltip(model, position), null);
});

test('synthetic 1–1, N–N and 1–N native regions extract exact inclusive sequence slices', () => {
  const base = feature('C');
  const track = base.tracks.find((item): item is RegionFeatureTrack => item.id === 'lreca-critical' && item.kind === 'region')!;
  track.regions = [
    { ...track.regions[0], id: 'first', start: 1, end: 1, length: 1, score: 0, isPrimary: false },
    { ...track.regions[0], id: 'last', start: 248, end: 248, length: 1, score: 1, isPrimary: false },
    { ...track.regions[0], id: 'whole', start: 1, end: 248, length: 248, score: 0.5, isPrimary: true },
  ];
  const model = buildSequenceViewerModel(base);
  const byId = (id: string) => model.regions.find((region) => region.id === id)!;
  assert.equal(extractSelectedRegionSequence(model, byId('first')), canonical[0]);
  assert.equal(extractSelectedRegionSequence(model, byId('last')), canonical[247]);
  assert.equal(extractSelectedRegionSequence(model, byId('whole')), canonical);
  assert.equal(residueCopyLabel(model, 1), 'M1'); assert.equal(residueCopyLabel(model, 243), 'R243'); assert.equal(residueCopyLabel(model, 248), 'T248');
  assert.equal(residueCopyLabel(model, 0), null); assert.equal(residueCopyLabel(model, 249), null);
  assert.equal(extractSelectedRegionSequence(model, { ...byId('first'), method: 'seg' }), null);
  assert.equal(extractSelectedRegionSequence(model, { ...byId('first'), id: 'stale-region' }), null);
});

test('0, 0.5 and 1 stay exact while display intensity only clamps presentation values', () => {
  const base = feature('A');
  const track = base.tracks.find((item): item is ContinuousFeatureTrack => item.id === 'lreca-attribution' && item.kind === 'continuous')!;
  track.values[0] = 0; track.values[1] = 0.5; track.values[2] = 1;
  const model = buildSequenceViewerModel(base);
  assert.deepEqual(model.residues.slice(0, 3).map((residue) => residue.lrecaAttribution), [0, 0.5, 1]);
  assert.deepEqual([displayIntensity(0), displayIntensity(0.5), displayIntensity(1)], [0, 0.5, 1]);
  assert.equal(displayIntensity(-0.25), 0); assert.equal(displayIntensity(1.25), 1);
  for (const value of [null, undefined, NaN, Infinity, -Infinity, '0.5']) assert.equal(displayIntensity(value), null);
  assert.deepEqual(track.values.slice(0, 3), [0, 0.5, 1]);
});

test('null pDP remains N/A while neighboring native values and FuzDrop regions remain available', () => {
  const base = feature('D');
  const track = base.tracks.find((item): item is ContinuousFeatureTrack => item.id === 'fuzdrop-propensity' && item.kind === 'continuous')!;
  track.values[44] = null;
  const model = buildSequenceViewerModel(base); const residue = model.residues[44];
  assert.equal(residue.fuzdropPropensity, null); assert.equal(residue.fuzdropPropensityStatus, 'not_provided');
  assert.equal(residue.fuzdropRegionMembership, 'yes'); assert.equal(residue.fuzdropRegions.length, 2);
  assert.equal(residue.tooltip.rows.find((row) => row.id === 'fuzdrop-propensity')!.text, 'N/A');
  assert.equal(option(model, 'fuzdrop-propensity').available, true);
});

test('an all-null imported pDP output is N/A and cannot enable a blank color scale', () => {
  const base = feature('D');
  const track = base.tracks.find((item): item is ContinuousFeatureTrack => item.id === 'fuzdrop-propensity' && item.kind === 'continuous')!;
  track.values.fill(null);
  const model = buildSequenceViewerModel(base);
  assert.equal(option(model, 'fuzdrop-propensity').available, false);
  assert.equal(option(model, 'fuzdrop-propensity').status, 'not_provided');
  assert.equal(model.residues[44].fuzdropPropensity, null);
  assert.equal(model.residues[44].fuzdropPropensityStatus, 'not_provided');
  assert.equal(model.residues[44].fuzdropRegionMembership, 'yes');
});

test('malformed NaN pDP isolates its color mode without damaging valid LRECA, FuzDrop regions or SEG', () => {
  const base = feature('D');
  const track = base.tracks.find((item): item is ContinuousFeatureTrack => item.id === 'fuzdrop-propensity' && item.kind === 'continuous')!;
  track.values[44] = NaN; const before = structuredClone(base);
  const model = buildSequenceViewerModel(base); const residue = model.residues[44];
  assert.equal(option(model, 'fuzdrop-propensity').available, false); assert.equal(option(model, 'fuzdrop-propensity').status, 'invalid');
  assert.equal(residue.fuzdropPropensityStatus, 'invalid'); assert.equal(residue.fuzdropPropensity, null);
  assert.equal(residue.lrecaAttributionStatus, 'value'); assert.equal(residue.fuzdropRegionMembership, 'yes'); assert.equal(residue.segMembership, 'no');
  assert.ok(model.issues.some((issue) => issue.outputId === 'fuzdrop-propensity' && issue.code === 'INVALID_TRACK'));
  assert.deepEqual(base, before);
});

test('a malformed optional region track is isolated and never creates membership from pDP', () => {
  const base = feature('D');
  const track = base.tracks.find((item): item is RegionFeatureTrack => item.id === 'fuzdrop-regions' && item.kind === 'region')!;
  track.regions[0].end = 249; const model = buildSequenceViewerModel(base);
  assert.equal(option(model, 'fuzdrop-regions').available, false); assert.equal(option(model, 'fuzdrop-regions').status, 'invalid');
  assert.equal(model.residues[44].fuzdropRegionMembership, 'invalid'); assert.deepEqual(model.residues[44].fuzdropRegions, []);
  assert.equal(model.residues[44].fuzdropPropensity, 0.1); assert.equal(option(model, 'fuzdrop-propensity').available, true);
  assert.equal(model.residues[44].segMembership, 'no'); assert.equal(model.residues[71].segMembership, 'yes');
});

test('non-array optional values and stale failed tracks are rejected or ignored without throwing', () => {
  const malformed = feature('D');
  const pdp = malformed.tracks.find((item) => item.id === 'fuzdrop-propensity')!;
  (pdp as unknown as { values: unknown }).values = null;
  assert.doesNotThrow(() => buildSequenceViewerModel(malformed));
  const rejected = buildSequenceViewerModel(malformed);
  assert.equal(option(rejected, 'fuzdrop-propensity').status, 'invalid');
  assert.equal(rejected.residues[44].fuzdropPropensityStatus, 'invalid');

  const stale = feature('B');
  const state = stale.outputStates.find((item) => item.id === 'seg-regions')!;
  state.status = 'failed'; state.message = 'Failed';
  const ignored = buildSequenceViewerModel(stale);
  assert.equal(option(ignored, 'seg-regions').available, false);
  assert.equal(ignored.residues[71].segMembership, 'failed');
  assert.deepEqual(ignored.residues[71].segRegions, []);
});

test('deeply frozen Module 7 model maps without mutation and output regions are fresh copies', () => {
  const base = deepFreeze(feature('D')); const before = JSON.stringify(base);
  const model = buildSequenceViewerModel(base); const original = base.tracks.find((item) => item.id === 'fuzdrop-regions');
  const copy = model.regions.find((region) => region.method === 'fuzdrop')!;
  assert.notEqual(copy, original && original.kind === 'region' ? original.regions[0] : null);
  copy.start = 999;
  assert.equal(JSON.stringify(base), before);
  assert.equal(model.residues[44].fuzdropRegions[0].start, 30);
});

test('empty and malformed parent models fail safely without inventing residues or enabling DisMeta', () => {
  const empty = buildSequenceViewerModel(buildFeatureViewerModel(null, null));
  assert.equal(empty.sequence, null); assert.equal(empty.length, 0); assert.deepEqual(empty.residues, []); assert.deepEqual(empty.regions, []);
  assert.equal(empty.defaultColorMode, 'none'); assert.equal(option(empty, 'none').available, true); assert.equal(option(empty, 'dismeta-regions').available, false);
  const bad = feature('A'); (bad as unknown as { sequence: string }).sequence = 'M'.repeat(247);
  assert.doesNotThrow(() => buildSequenceViewerModel(bad));
  const rejected = buildSequenceViewerModel(bad);
  assert.equal(rejected.sequence, null); assert.equal(rejected.length, 0); assert.deepEqual(rejected.residues, []);
  assert.ok(rejected.issues.some((issue) => issue.outputId === 'sequence' && issue.code === 'INVALID_SEQUENCE'));
});

for (const length of FEATURE_TEST_LENGTHS) {
  test(`synthetic ${length}-residue render fixture maps one lightweight record per 1-based residue`, async () => {
    const fixture = await createFeatureTestFixture(length);
    const featureModel = buildFeatureViewerModel(fixture.job, fixture.input);
    const model = buildSequenceViewerModel(featureModel);
    assert.equal(model.length, length); assert.equal(model.residues.length, length);
    assert.equal(model.residues[0].position, 1); assert.equal(model.residues[length - 1].position, length);
    assert.equal(model.residues[0].aa, fixture.input.canonical[0]); assert.equal(model.residues[length - 1].aa, fixture.input.canonical[length - 1]);
    assert.equal(model.issues.length, 0); assert.equal(model.colorModes.length, 7);
    assert.equal(getSequenceTooltip(model, length)!.position, length);
  });
}
