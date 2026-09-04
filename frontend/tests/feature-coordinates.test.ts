import test from 'node:test';
import assert from 'node:assert/strict';
import {
  brushDomain, coordinateTicks, domainLength, focusRegionDomain, focusResidueDomain,
  fullDomain, normalizeDomain, panDomain, positionToX, regionPixelBounds, xToPosition, zoomDomain,
} from '../src/lib/feature-coordinates.ts';
import type { ContinuousFeatureTrack, FeatureRegion, RegionFeatureTrack } from '../src/lib/feature-viewer-model.ts';
import { continuousScale, drawFeatureCanvas, featureTrackRows, hitTestRegion, paintedRegions } from '../src/lib/feature-plot-renderer.ts';

test('domains remain integer 1-based inclusive and invalid sequence lengths are not invented', () => {
  assert.deepEqual(fullDomain(526), { start: 1, end: 526 });
  assert.deepEqual(normalizeDomain({ start: 400.2, end: 200.4 }, 526), { start: 200, end: 400 });
  assert.deepEqual(normalizeDomain({ start: -10, end: 900 }, 526), fullDomain(526));
  assert.deepEqual(normalizeDomain({ start: NaN, end: 10 }, 526), fullDomain(526));
  for (const length of [0, -1, 1.5, NaN, Infinity]) assert.throws(() => fullDomain(length), RangeError);
});

for (const length of [1, 2, 100, 500, 1000, 2000, 5000]) {
  test(`every residue round-trips through one common pixel mapping at length ${length}`, () => {
    const domain = fullDomain(length);
    for (const width of [1, 317, 900]) {
      for (let position = 1; position <= length; position++) {
        assert.equal(xToPosition(positionToX(position, domain, width), domain, width), position);
      }
      assert.ok(positionToX(1, domain, width) > 0);
      assert.ok(positionToX(length, domain, width) < width);
      assert.equal(xToPosition(0, domain, width), 1);
      assert.equal(xToPosition(width, domain, width), length);
      assert.equal(xToPosition(-100, domain, width), 1);
      assert.equal(xToPosition(width + 100, domain, width), length);
    }
  });
}

test('zoomed coordinate round trips retain native positions, not local zero indices', () => {
  const domain = { start: 200, end: 400 };
  for (let position = 200; position <= 400; position++) assert.equal(xToPosition(positionToX(position, domain, 800), domain, 800), position);
  assert.deepEqual(brushDomain(0, 800, domain, 800), domain);
  assert.deepEqual(brushDomain(positionToX(320, domain, 800), positionToX(240, domain, 800), domain, 800), { start: 240, end: 320 });
});

test('one-residue and terminal regions are visible and hit-testable without changing native coordinates', () => {
  const domain = fullDomain(5000);
  const first = { start: 1, end: 1 };
  const last = { start: 5000, end: 5000 };
  const firstPixels = regionPixelBounds(first, domain, 500)!;
  const lastPixels = regionPixelBounds(last, domain, 500)!;
  assert.deepEqual(firstPixels, { left: 0, right: 3, width: 3 });
  assert.deepEqual(lastPixels, { left: 497, right: 500, width: 3 });
  assert.deepEqual(first, { start: 1, end: 1 });
  assert.deepEqual(last, { start: 5000, end: 5000 });
  assert.deepEqual(regionPixelBounds({ start: 1, end: 1 }, fullDomain(1), 200), { left: 0, right: 200, width: 200 });
});

test('region clipping uses inclusive cells and hides only fully out-of-view regions', () => {
  const domain = { start: 200, end: 400 };
  assert.equal(regionPixelBounds({ start: 1, end: 199 }, domain, 804), null);
  assert.equal(regionPixelBounds({ start: 401, end: 500 }, domain, 804), null);
  assert.deepEqual(regionPixelBounds({ start: 190, end: 200 }, domain, 804), { left: 0, right: 4, width: 4 });
  assert.deepEqual(regionPixelBounds({ start: 400, end: 410 }, domain, 804), { left: 800, right: 804, width: 4 });
  assert.deepEqual(regionPixelBounds({ start: 250, end: 250 }, domain, 804), { left: 200, right: 204, width: 4 });
});

test('pan preserves span at both sequence boundaries and reset is exact', () => {
  const domain = { start: 200, end: 400 };
  assert.deepEqual(panDomain(domain, 526, -10000), { start: 1, end: 201 });
  assert.deepEqual(panDomain(domain, 526, 10000), { start: 326, end: 526 });
  assert.deepEqual(panDomain(fullDomain(526), 526, 100), fullDomain(526));
  assert.deepEqual(panDomain(domain, 526, NaN), domain);
});

test('wheel zoom stays anchored and cannot escape the sequence or stop above one residue', () => {
  const initial = fullDomain(5000);
  assert.deepEqual(zoomDomain(initial, 5000, 0.1, 1), { start: 1, end: 500 });
  assert.deepEqual(zoomDomain(initial, 5000, 0.1, 5000), { start: 4501, end: 5000 });
  const middle = zoomDomain(initial, 5000, 0.2, 2500.5);
  assert.deepEqual(middle, { start: 2001, end: 3000 });
  assert.deepEqual(zoomDomain(middle, 5000, 10), initial);
  let domain = fullDomain(100);
  for (let count = 0; count < 100; count++) domain = zoomDomain(domain, 100, 0.9);
  assert.equal(domainLength(domain), 1);
  assert.equal(domainLength(zoomDomain(domain, 100, 1.01)), 2);
  assert.deepEqual(zoomDomain(initial, 5000, NaN), initial);
});

test('focus creates a bounded native interval and preserves single-residue regions', () => {
  assert.deepEqual(focusResidueDomain(1, 526), { start: 1, end: 51 });
  assert.deepEqual(focusResidueDomain(526, 526), { start: 476, end: 526 });
  assert.deepEqual(focusResidueDomain(243, 526), { start: 218, end: 268 });
  assert.deepEqual(focusResidueDomain(1, 1), fullDomain(1));
  assert.deepEqual(focusRegionDomain({ start: 65, end: 293 }, 526), { start: 45, end: 313 });
  assert.deepEqual(focusRegionDomain({ start: 526, end: 526 }, 526), { start: 506, end: 526 });
  assert.deepEqual(focusRegionDomain({ start: 7, end: 7 }, 20, 0), { start: 7, end: 7 });
});

test('coordinate ticks always include the visible first and last residues with no zero', () => {
  for (const domain of [fullDomain(1), fullDomain(526), { start: 200, end: 400 }]) {
    const ticks = coordinateTicks(domain, 700);
    assert.equal(ticks[0], domain.start);
    assert.equal(ticks[ticks.length - 1], domain.end);
    assert.equal(new Set(ticks).size, ticks.length);
    assert.ok(ticks.every((position) => Number.isInteger(position) && position >= 1));
  }
});

// Synthetic geometry fixtures only: these are not claimed to be scientific predictions.
function region(id: string, start: number, end: number): FeatureRegion {
  return { id, method: 'seg', type: 'low_complexity_region', label: 'Low-complexity region', start, end,
    length: end - start + 1, semanticType: 'region_annotation' };
}
function regionTrack(regions: FeatureRegion[]): RegionFeatureTrack {
  return { id: 'seg-regions', kind: 'region', method: 'seg', label: 'SEG', description: 'Test fixture', semanticType: 'region_annotation', regions };
}

test('paint and hit-test use identical terminal bounds and return original region objects', () => {
  const first = region('first', 1, 1);
  const last = region('last', 5000, 5000);
  const track = regionTrack([first, last]);
  const rows = featureTrackRows([track]);
  const domain = fullDomain(5000);
  const painted = paintedRegions(track, domain, 500, rows[0].top);
  assert.equal(hitTestRegion(rows, domain, 500, 0, painted[0].top + 4), first);
  assert.equal(hitTestRegion(rows, domain, 500, 500, painted[1].top + 4), last);
  assert.equal(hitTestRegion(rows, domain, 500, 250, painted[0].top + 4), null);
  assert.equal(hitTestRegion(rows, domain, 500, 0, 0), null);
});

test('overlap lanes preserve duplicates and primary status without deriving a winner', () => {
  const first = region('same-1', 10, 20);
  const second = region('same-2', 10, 20);
  const third = { ...region('primary', 15, 18), isPrimary: true, score: 0.123456789 };
  const track = regionTrack([first, second, third]);
  const before = structuredClone(track);
  const painted = paintedRegions(track, fullDomain(100), 500, 38);
  assert.equal(painted.length, 3);
  assert.equal(painted[0].region, first);
  assert.equal(painted[1].region, second);
  assert.equal(painted[2].region, third);
  assert.notEqual(painted[0].top, painted[1].top);
  assert.equal(painted[2].region.score, 0.123456789);
  assert.deepEqual(track, before);
});

test('empty successful region tracks remain rows but cannot produce a region hit', () => {
  const track = regionTrack([]);
  const rows = featureTrackRows([track]);
  assert.deepEqual(rows.map(({ top, height }) => ({ top, height })), [{ top: 38, height: 50 }]);
  assert.deepEqual(paintedRegions(track, fullDomain(100), 500, 38), []);
  assert.equal(hitTestRegion(rows, fullDomain(100), 500, 50, 55), null);
});

test('KDE visual scaling retains signed values and never substitutes probabilities', () => {
  const values = [-0.234567891, null, 1.987654321, 0];
  const track: ContinuousFeatureTrack = { id: 'lreca-kde', kind: 'continuous', method: 'lreca', label: 'KDE',
    description: 'Test fixture', semanticType: 'derived_hotspot', values, valueLabel: 'Contribution density', valueDomain: null };
  assert.deepEqual(continuousScale(track), [-0.234567891, 1.987654321]);
  assert.deepEqual(values, [-0.234567891, null, 1.987654321, 0]);
  assert.deepEqual(continuousScale({ ...track, values: [0, 0] }), [0, 1]);
  assert.deepEqual(continuousScale({ ...track, valueDomain: [0, 1] }), [0, 1]);
});

test('canvas timing retains first, latest and maximum completed draw, excluding hidden or unsupported canvas', (context) => {
  // Instrumentation fixture only; this fake context does not measure browser rendering speed.
  const timestamps = [10, 14, 30, 32, 40, 47, 50];
  const timer = context.mock.method(performance, 'now', () => timestamps.shift()!);
  const previousStyleGetter = Object.getOwnPropertyDescriptor(globalThis, 'getComputedStyle');
  Object.defineProperty(globalThis, 'getComputedStyle', { configurable: true, value: () => ({
    getPropertyValue: () => '', color: 'black', fontFamily: 'sans-serif',
  }) });
  const noop = () => {};
  const drawingContext = { setTransform: noop, fillRect: noop, beginPath: noop, moveTo: noop, lineTo: noop, stroke: noop, fillText: noop };
  const canvas = { dataset: {}, width: 0, height: 0, getContext: () => drawingContext } as unknown as HTMLCanvasElement;
  try {
    drawFeatureCanvas(canvas, [], fullDomain(100), 0, 1);
    assert.deepEqual(canvas.dataset, {});
    assert.equal(timer.mock.callCount(), 0);
    drawFeatureCanvas(canvas, [], fullDomain(100), 600, 1);
    assert.equal(canvas.dataset.staticFirstDrawMs, '4');
    drawFeatureCanvas(canvas, [], { start: 20, end: 40 }, 600, 1);
    assert.equal(canvas.dataset.staticDrawMs, '2');
    assert.equal(canvas.dataset.staticLastDrawMs, '2');
    assert.equal(canvas.dataset.staticDrawMaxMs, '4');
    drawFeatureCanvas(canvas, [], fullDomain(100), 600, 1);
    assert.equal(canvas.dataset.staticFirstDrawMs, '4');
    assert.equal(canvas.dataset.staticDrawMs, '7');
    assert.equal(canvas.dataset.staticLastDrawMs, '7');
    assert.equal(canvas.dataset.staticDrawMaxMs, '7');
    assert.equal(canvas.dataset.staticDrawCount, '3');
    const unsupported = { dataset: {}, getContext: () => null } as unknown as HTMLCanvasElement;
    drawFeatureCanvas(unsupported, [], fullDomain(100), 600, 1);
    assert.deepEqual(unsupported.dataset, {});
  } finally {
    if (previousStyleGetter) Object.defineProperty(globalThis, 'getComputedStyle', previousStyleGetter);
    else Reflect.deleteProperty(globalThis, 'getComputedStyle');
  }
});
