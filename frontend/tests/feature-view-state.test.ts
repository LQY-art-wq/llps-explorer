import assert from 'node:assert/strict';
import test from 'node:test';
import { createFeatureViewState, updateFeatureView } from '../src/lib/feature-view-state.ts';

test('zoom, visibility, and pan mode are visual state and do not mutate earlier state', () => {
  const initial = createFeatureViewState('first', 2000);
  const zoomed = updateFeatureView(initial, { type: 'domain', domain: { start: 200, end: 400 } }, 2000);
  const hidden = updateFeatureView(zoomed, { type: 'toggle', id: 'lreca-kde' }, 2000);
  const brush = updateFeatureView(hidden, { type: 'mode', mode: 'select' }, 2000);
  assert.deepEqual(initial.domain, { start: 1, end: 2000 });
  assert.deepEqual(brush.domain, { start: 200, end: 400 });
  assert.deepEqual(zoomed.hiddenTrackIds, []);
  assert.deepEqual(brush.hiddenTrackIds, ['lreca-kde']);
  assert.equal(brush.interactionMode, 'select');
  assert.deepEqual(updateFeatureView(brush, { type: 'toggle', id: 'lreca-kde' }, 2000).hiddenTrackIds, []);
});
test('reset zoom retains a user hidden track, while a new analysis clears visual state', () => {
  const previous = { ...createFeatureViewState('old', 5000), domain: { start: 4200, end: 4300 },
    hiddenTrackIds: ['seg-regions' as const], interactionMode: 'select' as const };
  const reset = updateFeatureView(previous, { type: 'reset' }, 5000);
  assert.deepEqual(reset.domain, { start: 1, end: 5000 });
  assert.deepEqual(reset.hiddenTrackIds, ['seg-regions']);
  assert.equal(updateFeatureView(previous, { type: 'analysis', analysisId: 'old' }, 5000), previous);
  const next = updateFeatureView(previous, { type: 'analysis', analysisId: 'new' }, 100);
  assert.deepEqual(next, createFeatureViewState('new', 100));
});
test('external domain requests remain integer 1-based inclusive and within this protein', () => {
  const initial = createFeatureViewState('short', 100);
  assert.deepEqual(updateFeatureView(initial, { type: 'domain', domain: { start: -20, end: 9999 } }, 100).domain,
    { start: 1, end: 100 });
  assert.deepEqual(updateFeatureView(initial, { type: 'domain', domain: { start: 100, end: 100 } }, 100).domain,
    { start: 100, end: 100 });
});
