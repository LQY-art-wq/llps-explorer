import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createViewerSelectionState, reduceViewerSelection,
} from '../src/lib/viewer-selection.ts';
import type { ViewerRegionSelection } from '../src/lib/viewer-data.ts';

const region: ViewerRegionSelection = {
  method: 'seg', id: 'seg-regions:1:89-119', type: 'low_complexity_region',
  start: 89, end: 119, semanticType: 'region_annotation',
};

test('ordinary Feature or Sequence residue clicks update one selection without tab or focus side effects', () => {
  const initial = createViewerSelectionState('features');
  const fromFeature = reduceViewerSelection(initial, { type: 'select_residue', position: 243 });
  assert.deepEqual(fromFeature, {
    ...initial, selectedResidue: 243,
  });
  const sequenceOpen = reduceViewerSelection(fromFeature, { type: 'set_tab', tab: 'sequence' });
  const fromSequence = reduceViewerSelection(sequenceOpen, { type: 'select_residue', position: 106 });
  assert.equal(fromSequence.activeTab, 'sequence');
  assert.equal(fromSequence.selectedResidue, 106);
  assert.equal(fromSequence.selectedRegion, null);
  assert.equal(fromSequence.featureFocusRequest, null);
  assert.equal(fromSequence.sequenceFocusRequest, null);
});

test('explicit residue links switch only their destination and issue independent focus requests', () => {
  let state = createViewerSelectionState('tables');
  state = reduceViewerSelection(state, { type: 'view_residue', destination: 'features', position: 243 });
  assert.equal(state.activeTab, 'features');
  assert.deepEqual(state.featureFocusRequest, { start: 243, end: 243, requestId: 1 });
  assert.equal(state.sequenceFocusRequest, null);
  state = reduceViewerSelection(state, { type: 'view_residue', destination: 'sequence', position: 106 });
  assert.equal(state.activeTab, 'sequence');
  assert.equal(state.selectedResidue, 106);
  assert.deepEqual(state.sequenceFocusRequest, { start: 106, end: 106, requestId: 1 });
  assert.deepEqual(state.featureFocusRequest, { start: 243, end: 243, requestId: 1 });
});

test('region selection preserves source identity without switching views or forcing either viewport', () => {
  const initial = createViewerSelectionState('features');
  const selected = reduceViewerSelection(initial, { type: 'select_region', region });
  assert.equal(selected.activeTab, 'features');
  assert.equal(selected.selectedResidue, null);
  assert.deepEqual(selected.selectedRegion, region);
  assert.notEqual(selected.selectedRegion, region);
  assert.equal(selected.featureFocusRequest, null);
  assert.equal(selected.sequenceFocusRequest, null);
});

test('explicit region links focus only the requested viewer and retain inclusive native endpoints', () => {
  let state = reduceViewerSelection(createViewerSelectionState('annotations'), {
    type: 'view_region', destination: 'sequence', region,
  });
  assert.equal(state.activeTab, 'sequence');
  assert.deepEqual(state.sequenceFocusRequest, { start: 89, end: 119, requestId: 1 });
  assert.equal(state.featureFocusRequest, null);
  state = reduceViewerSelection(state, { type: 'view_selected', destination: 'features' });
  assert.equal(state.activeTab, 'features');
  assert.deepEqual(state.featureFocusRequest, { start: 89, end: 119, requestId: 1 });
  assert.deepEqual(state.sequenceFocusRequest, { start: 89, end: 119, requestId: 1 });
  assert.deepEqual(state.selectedRegion, region);
});

test('repeated explicit navigation increments only the destination request identity', () => {
  let state = reduceViewerSelection(createViewerSelectionState(), {
    type: 'view_residue', destination: 'features', position: 1,
  });
  state = reduceViewerSelection(state, { type: 'view_selected', destination: 'features' });
  assert.equal(state.featureFocusRequest?.requestId, 2);
  assert.equal(state.sequenceFocusRequest, null);
  state = reduceViewerSelection(state, { type: 'view_selected', destination: 'sequence' });
  assert.equal(state.sequenceFocusRequest?.requestId, 1);
  assert.equal(state.featureFocusRequest?.requestId, 2);
});

test('table actions have explicit Feature and Sequence destinations over the same selection', () => {
  const initial = createViewerSelectionState('tables');
  const feature = reduceViewerSelection(initial, {
    type: 'view_region', destination: 'features', region,
  });
  const sequence = reduceViewerSelection(initial, {
    type: 'view_region', destination: 'sequence', region,
  });
  assert.equal(feature.activeTab, 'features');
  assert.equal(sequence.activeTab, 'sequence');
  assert.deepEqual(feature.selectedRegion, sequence.selectedRegion);
  assert.deepEqual(feature.featureFocusRequest, { start: 89, end: 119, requestId: 1 });
  assert.deepEqual(sequence.sequenceFocusRequest, { start: 89, end: 119, requestId: 1 });
});

test('a new result session starts with no stale residue, region, or scroll targets', () => {
  const previous = reduceViewerSelection(createViewerSelectionState(), {
    type: 'view_residue', destination: 'sequence', position: 243,
  });
  assert.equal(previous.selectedResidue, 243);
  // ResultsWorkspace keys ResultContent by job/result identity and constructs this fresh state.
  assert.deepEqual(createViewerSelectionState(), {
    activeTab: 'overview', selectedResidue: null, selectedRegion: null,
    featureFocusRequest: null, sequenceFocusRequest: null,
  });
});

test('clearing selection clears both pending focus targets while keeping the current tab', () => {
  let state = reduceViewerSelection(createViewerSelectionState(), {
    type: 'view_region', destination: 'features', region,
  });
  state = reduceViewerSelection(state, { type: 'view_selected', destination: 'sequence' });
  state = reduceViewerSelection(state, { type: 'clear' });
  assert.deepEqual(state, createViewerSelectionState('sequence'));
});

test('invalid external positions or intervals cannot become shared selection targets', () => {
  const initial = createViewerSelectionState('tables');
  assert.equal(reduceViewerSelection(initial, {
    type: 'view_residue', destination: 'features', position: 0,
  }), initial);
  assert.equal(reduceViewerSelection(initial, {
    type: 'select_region', region: { ...region, start: 120 },
  }), initial);
});
