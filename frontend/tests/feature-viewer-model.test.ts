/** Rendering-only tests over frozen Module 6 responses; mutations are explicit test cases. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import type { AnalysisJob, InputSnapshot, LRECAResult, FuzDropResult, SEGResult } from '../src/lib/contracts.ts';
import { buildFeatureViewerModel, getFeatureTooltip } from '../src/lib/feature-viewer-model.ts';
import type { FeatureOutputId, FeatureTrackId, FeatureViewerModel } from '../src/lib/feature-viewer-model.ts';

const evidence = new URL('../../docs/audit/module6_browser/api/', import.meta.url);
const saved = Object.fromEntries(['A', 'B', 'C', 'F', 'H'].map((name) => [name,
  JSON.parse(readFileSync(new URL(`${name}_job.json`, evidence), 'utf8')) as AnalysisJob]));
const sequence = (saved.C.methods.lreca!.result as LRECAResult).sequence;
function fixture(name = 'C'): AnalysisJob { return structuredClone(saved[name]); }
function input(job = saved.C): InputSnapshot {
  return { rawSequence: `>human_positive_line_1\n${sequence}`, canonical: sequence,
    sequenceName: job.sequence.name, length: job.sequence.length, validResidues: sequence.length,
    inputType: 'fasta', submittedAt: job.created_at };
}
function full(): AnalysisJob {
  // The C and F responses have the same canonical sequence. This combination exists only in tests.
  const job = fixture(); job.methods.fuzdrop = fixture('F').methods.fuzdrop;
  job.selected_methods.push('fuzdrop'); return job;
}
function lreca(job: AnalysisJob) { return job.methods.lreca!.result as LRECAResult; }
function fuzdrop(job: AnalysisJob) { return job.methods.fuzdrop!.result as FuzDropResult; }
function seg(job: AnalysisJob) { return job.methods.seg!.result as SEGResult; }
function state(model: FeatureViewerModel, id: FeatureOutputId) {
  const result = model.outputStates.find((row) => row.id === id); assert.ok(result); return result;
}
function track(model: FeatureViewerModel, id: FeatureTrackId) {
  const result = model.tracks.find((row) => row.id === id); assert.ok(result); return result;
}
function row(model: FeatureViewerModel, position: number, id: FeatureOutputId) {
  const result = getFeatureTooltip(model, position)?.rows.find((item) => item.id === id); assert.ok(result); return result;
}
function frozen<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) frozen(child);
    Object.freeze(value);
  }
  return value;
}
const allIds = ['lreca-attribution', 'lreca-kde', 'lreca-critical', 'fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions'];

test('no analysis has no invented sequence, residue values, regions, or IDR track', () => {
  const model = buildFeatureViewerModel(null, input());
  assert.equal(model.analysisId, null); assert.equal(model.sequence, null); assert.equal(model.length, 0);
  assert.deepEqual(model.tracks, []); assert.equal(getFeatureTooltip(model, 1), null);
  assert.equal(state(model, 'dismeta-regions').status, 'unavailable');
});
test('real LRECA full response retains the native values, precision, semantics, and primary flags', () => {
  const job = fixture('A'); const source = lreca(job); const model = buildFeatureViewerModel(job, input(job));
  assert.equal(model.analysisId, job.job_id); assert.equal(model.sequence, sequence); assert.equal(model.length, 248);
  assert.deepEqual(model.tracks.map((item) => item.id), allIds.slice(0, 3));
  const attr = track(model, 'lreca-attribution'); const kde = track(model, 'lreca-kde'); const regions = track(model, 'lreca-critical');
  assert.equal(attr.kind, 'continuous'); assert.equal(kde.kind, 'continuous'); assert.equal(regions.kind, 'region');
  if (attr.kind !== 'continuous' || kde.kind !== 'continuous' || regions.kind !== 'region') return;
  assert.deepEqual(attr.values, source.residue_attribution!.map((item) => item.score));
  assert.deepEqual(kde.values, source.kde!.values); assert.deepEqual(attr.valueDomain, [0, 1]); assert.equal(kde.valueDomain, null);
  assert.equal(attr.semanticType, 'model_attribution'); assert.equal(kde.semanticType, 'derived_hotspot');
  assert.deepEqual(regions.regions.map((region) => region.isPrimary), source.critical_regions!.map((region) => region.is_primary));
  assert.deepEqual(regions.regions.map((region) => region.score), source.critical_regions!.map((region) => region.score));
  const precise = attr.values.find((value) => value !== null && value !== Number(value.toFixed(3)));
  assert.notEqual(precise, undefined, 'Actual values remain more precise than their display text.');
});
test('real SEG-only analysis has one aligned annotation track and never needs LRECA', () => {
  const job = fixture('B'); const model = buildFeatureViewerModel(job, input(job));
  assert.deepEqual(model.tracks.map((item) => item.id), ['seg-regions']);
  const regions = track(model, 'seg-regions'); assert.equal(regions.kind, 'region');
  if (regions.kind !== 'region') return;
  assert.deepEqual(regions.regions.map(({ start, end, length }) => ({ start, end, length })),
    [{ start: 72, end: 85, length: 14 }, { start: 89, end: 119, length: 31 }, { start: 196, end: 247, length: 52 }]);
  assert.equal(row(model, 72, 'seg-regions').text, 'Yes'); assert.equal(row(model, 85, 'seg-regions').text, 'Yes');
  assert.equal(row(model, 86, 'seg-regions').text, 'No'); assert.equal(row(model, 248, 'seg-regions').text, 'No');
  assert.equal(state(model, 'lreca-attribution').status, 'not_selected');
});
test('real combined C keeps the scientific track order and separates FuzDrop/DisMeta states', () => {
  const model = buildFeatureViewerModel(fixture(), input());
  assert.deepEqual(model.tracks.map((item) => item.id), ['lreca-attribution', 'lreca-kde', 'lreca-critical', 'seg-regions']);
  assert.equal(row(model, 1, 'fuzdrop-propensity').text, 'Not imported');
  assert.equal(row(model, 1, 'dismeta-regions').text, 'Unavailable');
  assert.equal(model.tracks.some((item) => String(item.method) === 'dismeta'), false);
});
test('real normalized FuzDrop values and regions map after LRECA and before SEG without Sbind substitution', () => {
  const job = full(); const model = buildFeatureViewerModel(job, input(job));
  assert.deepEqual(model.tracks.map((item) => item.id), allIds);
  const pdp = track(model, 'fuzdrop-propensity'); assert.equal(pdp.kind, 'continuous');
  if (pdp.kind !== 'continuous') return;
  assert.deepEqual(pdp.values, fuzdrop(job).residue_propensity!.map((item) => item.score));
  assert.equal(pdp.valueLabel, 'pDP'); assert.equal(pdp.semanticType, 'residue_propensity');
  assert.equal(pdp.values[0], 0.1); assert.notEqual(pdp.values[0], fuzdrop(job).residue_propensity![0].Sbind);
  assert.deepEqual(row(model, 45, 'fuzdrop-regions').regions.map(({ start, end }) => [start, end]), [[30, 45], [45, 60]]);
});
test('FuzDrop global-only import generates neither a propensity curve nor inferred regions', () => {
  const job = fixture('F'); fuzdrop(job).residue_propensity = null; fuzdrop(job).regions = null;
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(model.tracks.some((item) => item.method === 'fuzdrop'), false);
  assert.equal(row(model, 1, 'fuzdrop-propensity').text, 'N/A'); assert.equal(row(model, 1, 'fuzdrop-regions').text, 'N/A');
  assert.equal(fuzdrop(job).raw_score, 0.68);
});
test('FuzDrop regions-only and residue-only imports independently expose their supplied outputs', () => {
  const regionJob = fixture('F'); fuzdrop(regionJob).residue_propensity = null;
  assert.deepEqual(buildFeatureViewerModel(regionJob, input(regionJob)).tracks.filter((item) => item.method === 'fuzdrop').map((item) => item.id), ['fuzdrop-regions']);
  const residueJob = fixture('F'); fuzdrop(residueJob).regions = null;
  assert.deepEqual(buildFeatureViewerModel(residueJob, input(residueJob)).tracks.filter((item) => item.method === 'fuzdrop').map((item) => item.id), ['fuzdrop-propensity']);
});
test('all-null pDP produces N/A instead of a zero curve; mixed nulls remain actual gaps', () => {
  const job = fixture('F'); fuzdrop(job).residue_propensity!.forEach((item) => { item.score = null; });
  let model = buildFeatureViewerModel(job, input(job));
  assert.equal(model.tracks.some((item) => item.id === 'fuzdrop-propensity'), false);
  assert.equal(row(model, 1, 'fuzdrop-propensity').text, 'N/A');
  fuzdrop(job).residue_propensity![1].score = 0.123456789123;
  fuzdrop(job).residue_propensity![2].score = 0;
  model = buildFeatureViewerModel(job, input(job));
  assert.equal(row(model, 1, 'fuzdrop-propensity').value, null);
  assert.equal(row(model, 2, 'fuzdrop-propensity').value, 0.123456789123);
  assert.equal(row(model, 3, 'fuzdrop-propensity').value, 0);
  assert.equal(row(model, 3, 'fuzdrop-propensity').status, 'value');
});
test('successful empty regions mean No, missing output N/A, unimported FuzDrop Not imported, blocked DisMeta Unavailable', () => {
  const job = fixture(); seg(job).regions = []; lreca(job).critical_regions = null;
  const model = buildFeatureViewerModel(job, input(job)); const empty = track(model, 'seg-regions');
  assert.equal(empty.kind, 'region'); if (empty.kind === 'region') assert.deepEqual(empty.regions, []);
  assert.equal(state(model, 'seg-regions').status, 'empty'); assert.equal(row(model, 1, 'seg-regions').text, 'No');
  assert.equal(row(model, 1, 'lreca-critical').text, 'N/A'); assert.equal(row(model, 1, 'fuzdrop-regions').text, 'Not imported');
  assert.equal(row(model, 1, 'dismeta-regions').text, 'Unavailable');
  assert.equal(row(model, 1, 'seg-regions').value, null);
});
test('actual test-only H partial success preserves LRECA while SEG is Failed, not No', () => {
  const job = fixture('H'); const model = buildFeatureViewerModel(job, input(job));
  assert.equal(job.status, 'partial_success'); assert.deepEqual(model.tracks.map((item) => item.id), allIds.slice(0, 3));
  assert.equal(row(model, 1, 'seg-regions').status, 'failed'); assert.equal(row(model, 1, 'seg-regions').text, 'Failed');
});
for (const [status, expected] of [['queued', 'pending'], ['running', 'pending'], ['failed', 'failed'], ['unavailable', 'unavailable'], ['skipped', 'not_selected']] as const) {
  test(`${status} execution never exposes stale successful arrays`, () => {
    const job = fixture(); job.methods.lreca!.status = status;
    const model = buildFeatureViewerModel(job, input(job));
    assert.deepEqual(model.tracks.map((item) => item.id), ['seg-regions']); assert.equal(state(model, 'lreca-attribution').status, expected);
  });
}
test('external-result-required is Not imported while a forged DisMeta success still has no track', () => {
  const job = full(); job.methods.fuzdrop!.status = 'external_result_required';
  job.selected_methods.push('dismeta');
  job.methods.dismeta = { ...job.methods.seg!, method: 'dismeta', status: 'success' };
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'fuzdrop-propensity').status, 'not_imported');
  assert.equal(state(model, 'dismeta-regions').status, 'unavailable');
  assert.equal(model.tracks.some((item) => String(item.method) === 'dismeta'), false);
});
test('unselected native payloads cannot add an output to a historical job', () => {
  const job = full(); job.selected_methods = ['seg'];
  assert.deepEqual(buildFeatureViewerModel(job, input(job)).tracks.map((item) => item.id), ['seg-regions']);
});
test('successful global-only LRECA and unavailable KDE do not get zero attribution/density', () => {
  const job = fixture(); lreca(job).attribution_status = 'not_requested'; lreca(job).residue_attribution = null;
  lreca(job).kde = null; lreca(job).critical_regions = null;
  const model = buildFeatureViewerModel(job, input(job));
  assert.deepEqual(model.tracks.map((item) => item.id), ['seg-regions']); assert.equal(row(model, 1, 'lreca-attribution').text, 'N/A');
  const short = fixture(); lreca(short).kde!.status = 'unavailable'; lreca(short).kde!.values = null;
  lreca(short).kde!.regions = null; lreca(short).critical_regions = null;
  assert.equal(state(buildFeatureViewerModel(short, input(short)), 'lreca-kde').status, 'not_provided');
});

const residueMutations: [string, (rows: Record<string, unknown>[]) => void][] = [
  ['length', (rows) => { rows.pop(); }], ['zero position', (rows) => { rows[0].position = 0; }],
  ['duplicate position', (rows) => { rows[1].position = 1; }], ['out-of-range position', (rows) => { rows[0].position = 249; }],
  ['wrong aa', (rows) => { rows[0].aa = 'Q'; }], ['wrong semantic', (rows) => { rows[0].semantic_type = 'region_annotation'; }],
  ['negative score', (rows) => { rows[0].score = -0.01; }], ['score above one', (rows) => { rows[0].score = 1.01; }],
  ['NaN', (rows) => { rows[0].score = Number.NaN; }], ['Infinity', (rows) => { rows[0].score = Infinity; }],
  ['boolean', (rows) => { rows[0].score = false; }], ['missing score', (rows) => { delete rows[0].score; }],
];
for (const id of ['lreca-attribution', 'fuzdrop-propensity'] as const) {
  for (const [label, mutate] of residueMutations) test(`${id} ${label} is isolated from every other optional track`, () => {
    const job = full(); const rows = id === 'lreca-attribution' ? lreca(job).residue_attribution : fuzdrop(job).residue_propensity;
    mutate(rows as unknown as Record<string, unknown>[]);
    const model = buildFeatureViewerModel(job, input(job));
    assert.equal(state(model, id).status, 'invalid'); assert.deepEqual(model.tracks.map((item) => item.id), allIds.filter((other) => other !== id));
    assert.deepEqual(model.issues.map((issue) => issue.outputId), [id]);
  });
}
test('pDP name is checked independently of Sbind, and null LRECA attribution is invalid', () => {
  const job = full(); (fuzdrop(job).residue_propensity![0] as unknown as Record<string, unknown>).score_name = 'Sbind';
  (lreca(job).residue_attribution![0] as unknown as Record<string, unknown>).score = null;
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'fuzdrop-propensity').status, 'invalid'); assert.equal(state(model, 'lreca-attribution').status, 'invalid');
  assert.equal(track(model, 'seg-regions').kind, 'region');
});
for (const invalid of [NaN, Infinity, null, true, '0.5']) test(`KDE invalid ${String(invalid)} stays isolated`, () => {
  const job = full(); (lreca(job).kde!.values as unknown[])[0] = invalid;
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'lreca-kde').status, 'invalid'); assert.deepEqual(model.tracks.map((item) => item.id), allIds.filter((id) => id !== 'lreca-kde'));
});
test('KDE density supports finite values outside [0,1] without probability clipping or recalculation', () => {
  const job = fixture(); lreca(job).kde!.values![0] = -0.123456789; lreca(job).kde!.values![1] = 12.3456789;
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(row(model, 1, 'lreca-kde').value, -0.123456789); assert.equal(row(model, 2, 'lreca-kde').value, 12.3456789);
});
test('short or wrongly typed KDE arrays are invalid without affecting critical regions', () => {
  for (const raw of [[], [0], 'invalid']) {
    const job = fixture(); (lreca(job).kde as unknown as Record<string, unknown>).values = raw;
    const model = buildFeatureViewerModel(job, input(job));
    assert.equal(state(model, 'lreca-kde').status, 'invalid'); assert.equal(track(model, 'lreca-critical').kind, 'region');
  }
});
const badRegionRows: [string, Record<string, unknown>][] = [
  ['zero', { start: 0 }], ['negative', { start: -1 }], ['reversed', { start: 90, end: 80 }],
  ['outside', { end: 249 }], ['fractional', { start: 1.5 }], ['string coordinate', { start: '1' }],
  ['boolean coordinate', { start: true }], ['incorrect length', { length: 999 }],
  ['semantic mismatch', { semantic_type: 'model_attribution' }],
];
for (const id of ['lreca-critical', 'fuzdrop-regions', 'seg-regions'] as const) {
  for (const [label, updates] of badRegionRows) test(`${id} rejects ${label} without filtering or breaking sibling outputs`, () => {
    const job = full(); const rows = id === 'lreca-critical' ? lreca(job).critical_regions! : id === 'fuzdrop-regions' ? fuzdrop(job).regions! : seg(job).regions;
    Object.assign(rows[0], updates);
    const model = buildFeatureViewerModel(job, input(job));
    assert.equal(state(model, id).status, 'invalid'); assert.deepEqual(model.tracks.map((item) => item.id), allIds.filter((other) => other !== id));
  });
}
test('1–1, N–N and 1–N remain inclusive at both ends; tooltip AA comes from the master sequence', () => {
  const job = fixture('B'); seg(job).regions = [
    { start: 1, end: 1, length: 1, semantic_type: 'region_annotation' },
    { start: 248, end: 248, length: 1, semantic_type: 'region_annotation' },
    { start: 1, end: 248, length: 248, semantic_type: 'region_annotation' },
  ];
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(getFeatureTooltip(model, 1)!.aa, sequence[0]); assert.equal(getFeatureTooltip(model, 248)!.aa, sequence[247]);
  assert.deepEqual(row(model, 1, 'seg-regions').regions.map(({ start, end }) => [start, end]), [[1, 1], [1, 248]]);
  assert.deepEqual(row(model, 248, 'seg-regions').regions.map(({ start, end }) => [start, end]), [[248, 248], [1, 248]]);
  for (const invalid of [0, -1, 249, 1.5, NaN, Infinity]) assert.equal(getFeatureTooltip(model, invalid), null);
});
test('native region order, overlaps and duplicates remain intact with distinct selection IDs', () => {
  const job = fixture('F'); const original = fuzdrop(job).regions!;
  fuzdrop(job).regions = [original[2], original[0], structuredClone(original[0]), original[1]];
  const model = buildFeatureViewerModel(job, input(job)); const result = track(model, 'fuzdrop-regions');
  assert.equal(result.kind, 'region'); if (result.kind !== 'region') return;
  assert.deepEqual(result.regions.map((region) => [region.start, region.end]), [[40, 42], [30, 45], [30, 45], [45, 60]]);
  assert.equal(new Set(result.regions.map((region) => region.id)).size, 4);
  assert.equal(row(model, 41, 'fuzdrop-regions').regions.length, 3);
});
test('primary follows is_primary even when a candidate has the larger score', () => {
  const job = fixture(); lreca(job).critical_regions = [
    { start: 1, end: 1, length: 1, score: 0.000000001, is_primary: true, semantic_type: 'derived_hotspot' },
    { start: 248, end: 248, length: 1, score: 999.123456789, is_primary: false, semantic_type: 'derived_hotspot' },
  ];
  const model = buildFeatureViewerModel(job, input(job)); const result = track(model, 'lreca-critical');
  assert.equal(result.kind, 'region'); if (result.kind !== 'region') return;
  assert.deepEqual(result.regions.map((region) => region.isPrimary), [true, false]);
  assert.equal(result.regions[0].label, 'Primary hotspot'); assert.equal(result.regions[1].label, 'Candidate hotspot');
  assert.equal(result.regions[1].score, 999.123456789);
});
test('invalid primary flags or FuzDrop region labels cannot silently acquire replacement semantics', () => {
  const job = full(); (lreca(job).critical_regions![0] as unknown as Record<string, unknown>).is_primary = 'true';
  (fuzdrop(job).regions![0] as unknown as Record<string, unknown>).official_type = 'IDR';
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'lreca-critical').status, 'invalid'); assert.equal(state(model, 'fuzdrop-regions').status, 'invalid');
  assert.ok(model.tracks.some((item) => item.id === 'seg-regions'));
});
test('paired normalized snapshot is authoritative and native sequence conflicts isolate the offending method', () => {
  const job = full(); lreca(job).sequence = 'Q'.repeat(248);
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(model.sequence, sequence); assert.equal(getFeatureTooltip(model, 1)!.aa, 'M');
  assert.deepEqual(model.tracks.map((item) => item.id), ['fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions']);
  assert.ok(model.issues.every((issue) => issue.code === 'SEQUENCE_MISMATCH'));
});
test('FuzDrop and SEG require sequence hashes paired to the current job', () => {
  const job = full(); fuzdrop(job).sequence_sha256 = '0'.repeat(64); seg(job).sequence_sha256 = '0'.repeat(64);
  const model = buildFeatureViewerModel(job, input(job));
  assert.deepEqual(model.tracks.map((item) => item.id), allIds.slice(0, 3));
  assert.equal(state(model, 'fuzdrop-regions').status, 'invalid'); assert.equal(state(model, 'seg-regions').status, 'invalid');
});
test('validated import provenance is required; direct remote or pasted-only data cannot create tracks', () => {
  const job = full(); fuzdrop(job).source = 'official_remote_service';
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'fuzdrop-propensity').status, 'invalid'); assert.equal(state(model, 'fuzdrop-regions').status, 'invalid');
  assert.equal(model.tracks.length, 4);
});
test('native canonical sequence is the fallback when a paired snapshot is unavailable', () => {
  assert.equal(buildFeatureViewerModel(fixture('A'), null).sequence, sequence);
  assert.equal(buildFeatureViewerModel(fixture('F'), null).sequence, sequence);
  const missing = buildFeatureViewerModel(fixture('B'), null);
  assert.equal(missing.sequence, null); assert.deepEqual(missing.tracks, []); assert.equal(missing.issues[0].code, 'INVALID_SEQUENCE');
});
test('a malformed or unselected native sequence cannot displace another valid sequence fallback', () => {
  const job = full(); (lreca(job) as unknown as Record<string, unknown>).sequence = null;
  let model = buildFeatureViewerModel(job, null);
  assert.equal(model.sequence, sequence);
  assert.deepEqual(model.tracks.map((item) => item.id), ['fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions']);
  lreca(job).sequence = 'Q'.repeat(248); job.selected_methods = ['fuzdrop', 'seg'];
  model = buildFeatureViewerModel(job, null);
  assert.equal(model.sequence, sequence); assert.equal(state(model, 'fuzdrop-propensity').status, 'success');
});
test('FuzDrop coordinate declaration must agree with the common one-based axis', () => {
  const job = full(); (fuzdrop(job) as unknown as Record<string, unknown>).coordinate_system = 'zero_based';
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'fuzdrop-regions').status, 'invalid');
  assert.deepEqual(model.tracks.map((item) => item.id), ['lreca-attribution', 'lreca-kde', 'lreca-critical', 'seg-regions']);
});
test('native failed status cannot be hidden by a successful execution envelope', () => {
  const job = full(); (lreca(job) as unknown as Record<string, unknown>).status = 'failed';
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'lreca-attribution').status, 'invalid');
  assert.deepEqual(model.tracks.map((item) => item.id), ['fuzdrop-propensity', 'fuzdrop-regions', 'seg-regions']);
});
test('valid backend-provided zero attribution values remain values rather than missing data', () => {
  const job = fixture(); lreca(job).residue_attribution!.forEach((residue) => { residue.score = 0; });
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(track(model, 'lreca-attribution').kind, 'continuous');
  assert.equal(row(model, 1, 'lreca-attribution').value, 0); assert.equal(row(model, 1, 'lreca-attribution').status, 'value');
});
test('malformed envelopes and optional arrays produce safe issues without raw diagnostic text', () => {
  const broken = fixture(); (broken as unknown as Record<string, unknown>).sequence = null;
  assert.doesNotThrow(() => buildFeatureViewerModel(broken, input()));
  const job = full(); (fuzdrop(job) as unknown as Record<string, unknown>).residue_propensity = 'private-server-path';
  const model = buildFeatureViewerModel(job, input(job));
  assert.equal(state(model, 'fuzdrop-propensity').status, 'invalid');
  assert.equal(JSON.stringify(model.issues).includes('private-server-path'), false);
});
test('mapping deeply frozen input is pure; output edits cannot mutate native values or coordinates', () => {
  const job = frozen(full()); const snapshot = frozen(input(job)); const before = JSON.stringify(job);
  const model = buildFeatureViewerModel(job, snapshot);
  const values = track(model, 'lreca-attribution'); if (values.kind === 'continuous') values.values[0] = 999;
  const regions = track(model, 'seg-regions'); if (regions.kind === 'region') regions.regions[0].start = 999;
  const tooltip = getFeatureTooltip(model, 45)!; tooltip.rows.find((item) => item.id === 'fuzdrop-regions')!.regions[0].start = 999;
  assert.equal(JSON.stringify(job), before); assert.equal(snapshot.canonical, sequence);
  assert.notEqual(row(model, 45, 'fuzdrop-regions').regions[0].start, 999);
});
