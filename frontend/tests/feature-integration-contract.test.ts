/** Cross-layer presentation contracts over frozen Module 6 evidence; no inference runs here. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import type { AnalysisJob, FuzDropResult, InputSnapshot, LRECAResult } from '../src/lib/contracts.ts';
import { brushDomain, focusRegionDomain, focusResidueDomain, fullDomain, panDomain, positionToX, xToPosition } from '../src/lib/feature-coordinates.ts';
import { featureTrackRows, hitTestRegion, paintedRegions } from '../src/lib/feature-plot-renderer.ts';
import { buildFeatureViewerModel, getFeatureTooltip } from '../src/lib/feature-viewer-model.ts';
import type { FeatureTrackId, FeatureViewerModel, RegionFeatureTrack } from '../src/lib/feature-viewer-model.ts';
import { createFeatureViewState, updateFeatureView } from '../src/lib/feature-view-state.ts';

const evidence = new URL('../../docs/audit/module6_browser/api/', import.meta.url);
function readJob(name: string): AnalysisJob {
  return JSON.parse(readFileSync(new URL(`${name}_job.json`, evidence), 'utf8')) as AnalysisJob;
}
const canonical = (readJob('C').methods.lreca!.result as LRECAResult).sequence;
function snapshot(job: AnalysisJob): InputSnapshot {
  return { rawSequence: `>human_positive_line_1\n${canonical}`, canonical, sequenceName: job.sequence.name,
    length: job.sequence.length, validResidues: canonical.length, inputType: 'fasta', submittedAt: job.created_at };
}
function combinedJob(): AnalysisJob {
  // C supplies real local outputs; F supplies the explicitly synthetic, validated browser import.
  // Combining their same-sequence method outputs is a test-only presentation fixture.
  const job = readJob('C');
  job.methods.fuzdrop = readJob('F').methods.fuzdrop;
  job.selected_methods.push('fuzdrop');
  return job;
}
function regionTrack(model: FeatureViewerModel, id: FeatureTrackId): RegionFeatureTrack {
  const track = model.tracks.find((item) => item.id === id);
  assert.ok(track?.kind === 'region');
  return track;
}
function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

test('table residue focus, shared domain and tooltip preserve all native values at three plot widths', () => {
  const job = combinedJob(); const model = buildFeatureViewerModel(job, snapshot(job));
  const native = job.methods.lreca!.result as LRECAResult;
  const pdp = (job.methods.fuzdrop!.result as FuzDropResult).residue_propensity!;
  const position = native.top_residues![0].position;
  let state = createFeatureViewState(model.analysisId, model.length);
  state = updateFeatureView(state, { type: 'domain', domain: focusResidueDomain(position, model.length) }, model.length);
  for (const width of [300, 628, 1064]) {
    const pixel = positionToX(position, state.domain, width);
    const tooltip = getFeatureTooltip(model, xToPosition(pixel, state.domain, width));
    assert.ok(tooltip);
    assert.equal(tooltip.position, position);
    assert.equal(tooltip.aa, canonical[position - 1]);
    assert.equal(tooltip.rows.find((row) => row.id === 'lreca-attribution')!.value, native.residue_attribution![position - 1].score);
    assert.equal(tooltip.rows.find((row) => row.id === 'lreca-kde')!.value, native.kde!.values![position - 1]);
    assert.equal(tooltip.rows.find((row) => row.id === 'fuzdrop-propensity')!.value, pdp[position - 1].score);
  }
});

test('native SEG table regions focus, paint and hit-test on the same inclusive sequence coordinates', () => {
  const job = readJob('B'); const model = buildFeatureViewerModel(job, snapshot(job));
  const track = regionTrack(model, 'seg-regions');
  for (const region of track.regions) {
    const domain = focusRegionDomain(region, model.length);
    const rows = featureTrackRows(model.tracks);
    const row = rows.find((item) => item.track.id === track.id)!;
    const painted = paintedRegions(track, domain, 628, row.top).find((item) => item.region.id === region.id)!;
    for (const position of [region.start, region.end]) {
      const x = positionToX(position, domain, 628);
      assert.ok(x >= painted.left && x <= painted.right);
      assert.equal(hitTestRegion(rows, domain, 628, x, painted.top + painted.height / 2)?.id, region.id);
      const tooltip = getFeatureTooltip(model, position)!;
      assert.equal(tooltip.aa, canonical[position - 1]);
      assert.ok(tooltip.rows.find((item) => item.id === track.id)!.regions.some((item) => item.id === region.id));
    }
    const outside = region.end + 1;
    assert.equal(getFeatureTooltip(model, outside)!.rows.find((item) => item.id === track.id)!.text, 'No');
  }
});

test('the shared FuzDrop endpoint keeps both native memberships while hit testing selects a distinct lane', () => {
  const job = readJob('F'); const model = buildFeatureViewerModel(job, snapshot(job));
  const track = regionTrack(model, 'fuzdrop-regions');
  const tooltip = getFeatureTooltip(model, 45)!;
  const memberships = tooltip.rows.find((row) => row.id === track.id)!.regions;
  assert.deepEqual(memberships.map((region) => [region.start, region.end]), [[30, 45], [45, 60]]);
  const domain = focusRegionDomain({ start: 30, end: 60 }, model.length);
  const rows = featureTrackRows(model.tracks);
  const row = rows.find((item) => item.track.id === track.id)!;
  const painted = paintedRegions(track, domain, 628, row.top);
  for (const region of memberships) {
    const bar = painted.find((item) => item.region.id === region.id)!;
    const hit = hitTestRegion(rows, domain, 628, positionToX(45, domain, 628), bar.top + bar.height / 2)!;
    assert.equal(hit.id, region.id);
    assert.equal(hit.type, region.type);
    assert.equal(hit.length, region.length);
    assert.equal(hit.semanticType, 'region_prediction');
    assert.equal('isPrimary' in hit, false);
  }
});

test('hiding, brushing, panning and resetting change presentation without changing downloadable evidence', () => {
  const job = deepFreeze(combinedJob()); const model = deepFreeze(buildFeatureViewerModel(job, snapshot(job)));
  const beforeJob = JSON.stringify(job), beforeModel = JSON.stringify(model);
  let state = createFeatureViewState(model.analysisId, model.length);
  state = updateFeatureView(state, { type: 'toggle', id: 'seg-regions' }, model.length);
  const full = fullDomain(model.length);
  state = updateFeatureView(state, { type: 'domain', domain: brushDomain(positionToX(72, full, 628), positionToX(119, full, 628), full, 628) }, model.length);
  assert.deepEqual(state.domain, { start: 72, end: 119 });
  state = updateFeatureView(state, { type: 'domain', domain: panDomain(state.domain, model.length, 50) }, model.length);
  assert.deepEqual(state.domain, { start: 122, end: 169 });
  const visible = model.tracks.filter((track) => !state.hiddenTrackIds.includes(track.id));
  assert.equal(featureTrackRows(visible).some((row) => row.track.id === 'seg-regions'), false);
  assert.equal(getFeatureTooltip(model, 72)!.rows.find((row) => row.id === 'seg-regions')!.text, 'Yes');
  state = updateFeatureView(state, { type: 'reset' }, model.length);
  assert.deepEqual(state.domain, full);
  assert.deepEqual(state.hiddenTrackIds, ['seg-regions']);
  assert.equal(JSON.stringify(job), beforeJob);
  assert.equal(JSON.stringify(model), beforeModel);
});

test('the actual partial-success job renders retained LRECA evidence and no artificial SEG bars', () => {
  const job = readJob('H'); const model = buildFeatureViewerModel(job, snapshot(job));
  assert.equal(job.status, 'partial_success');
  let state = createFeatureViewState(model.analysisId, model.length);
  state = updateFeatureView(state, { type: 'domain', domain: focusResidueDomain(248, model.length) }, model.length);
  assert.deepEqual(featureTrackRows(model.tracks).map((row) => row.track.id), ['lreca-attribution', 'lreca-kde', 'lreca-critical']);
  const position = xToPosition(positionToX(248, state.domain, 300), state.domain, 300);
  const tooltip = getFeatureTooltip(model, position)!;
  assert.equal(tooltip.aa, canonical[247]);
  assert.equal(tooltip.rows.find((row) => row.id === 'seg-regions')!.status, 'failed');
  assert.equal(tooltip.rows.find((row) => row.id === 'seg-regions')!.value, null);
  assert.equal(tooltip.rows.find((row) => row.id === 'lreca-attribution')!.value, (job.methods.lreca!.result as LRECAResult).residue_attribution![247].score);
  assert.equal(tooltip.rows.find((row) => row.id === 'dismeta-regions')!.text, 'Unavailable');
});

test('switching actual analysis IDs resets zoom and visibility while polling the same job preserves them', () => {
  const first = readJob('C'); const second = readJob('H');
  const firstModel = buildFeatureViewerModel(first, snapshot(first));
  const secondModel = buildFeatureViewerModel(second, snapshot(second));
  let state = createFeatureViewState(firstModel.analysisId, firstModel.length);
  state = updateFeatureView(state, { type: 'domain', domain: { start: 50, end: 70 } }, firstModel.length);
  state = updateFeatureView(state, { type: 'toggle', id: 'lreca-kde' }, firstModel.length);
  assert.equal(updateFeatureView(state, { type: 'analysis', analysisId: firstModel.analysisId }, firstModel.length), state);
  const next = updateFeatureView(state, { type: 'analysis', analysisId: secondModel.analysisId }, secondModel.length);
  assert.deepEqual(next.domain, fullDomain(secondModel.length));
  assert.deepEqual(next.hiddenTrackIds, []);
  assert.equal(next.analysisId, second.job_id);
  assert.equal(firstModel.analysisId, first.job_id);
});

test('a rejected optional pDP array leaves other rows hit-testable without converting absence into zero', () => {
  const job = combinedJob();
  (job.methods.fuzdrop!.result as FuzDropResult).residue_propensity!.pop();
  const model = buildFeatureViewerModel(job, snapshot(job));
  const rows = featureTrackRows(model.tracks);
  assert.equal(rows.some((row) => row.track.id === 'fuzdrop-propensity'), false);
  const track = regionTrack(model, 'fuzdrop-regions');
  const row = rows.find((item) => item.track.id === track.id)!;
  const domain = focusRegionDomain({ start: 30, end: 60 }, model.length);
  const bar = paintedRegions(track, domain, 300, row.top)[0];
  assert.equal(hitTestRegion(rows, domain, 300, positionToX(30, domain, 300), bar.top + bar.height / 2)?.id, bar.region.id);
  const tooltip = getFeatureTooltip(model, 30)!;
  assert.equal(tooltip.rows.find((item) => item.id === 'fuzdrop-propensity')!.status, 'invalid');
  assert.equal(tooltip.rows.find((item) => item.id === 'fuzdrop-propensity')!.value, null);
  assert.equal(tooltip.rows.find((item) => item.id === 'fuzdrop-regions')!.text, 'Yes');
  assert.equal(tooltip.rows.find((item) => item.id === 'seg-regions')!.text, 'No');
});
